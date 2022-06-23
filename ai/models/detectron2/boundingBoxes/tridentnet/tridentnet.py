'''
    TridentNet specifier for Detectron2 model trainer in AIDE.

    2021-22 Benjamin Kellenberger
'''

import os
import torch
from detectron2.config import get_cfg
import detectron2.utils.comm as comm
from ai.models.detectron2.boundingBoxes.tridentnet.tridentnet_detectron2.config import add_tridentnet_config

from ai.models.detectron2.genericDetectronModel import GenericDetectron2Model
from ai.models.detectron2.boundingBoxes.genericDetectronBBoxModel import GenericDetectron2BoundingBoxModel
from ai.models.detectron2.boundingBoxes.tridentnet import DEFAULT_OPTIONS
from util import optionsHelper


class TridentNet(GenericDetectron2BoundingBoxModel):

    def __init__(self, project, config, dbConnector, fileServer, options):
        super(TridentNet, self).__init__(project, config, dbConnector, fileServer, options)

        try:
            # check options
            if self.detectron2cfg.MODEL.META_ARCHITECTURE != 'GeneralizedRCNN':
                raise Exception(f'Invalid meta architecture ("{self.detectron2cfg.MODEL.META_ARCHITECTURE}" != "GeneralizedRCNN")')
            if self.detectron2cfg.MODEL.ROI_HEADS.NAME != 'TridentRes5ROIHeads':
                raise Exception(f'Invalid ROI head architecture ("{self.detectron2cfg.MODEL.ROI_HEADS.NAME}" != "TridentRes5ROIHeads")')
            if self.detectron2cfg.MODEL.PROPOSAL_GENERATOR.NAME != 'TridentRPN':
                raise Exception(f'Invalid proposal generator ("{self.detectron2cfg.MODEL.PROPOSAL_GENERATOR.NAME}" != "TridentRPN")')
            assert hasattr(self.detectron2cfg.MODEL, 'TRIDENT'), 'Missing "TRIDENT" option'
        except Exception as e:
            print(f'[{self.project}] WARNING: provided options are not valid for TridentNet (message: "{str(e)}"); falling back to defaults.')
            self.options = self.getDefaultOptions()
            self.detectron2cfg = self._get_config()
            self.detectron2cfg = GenericDetectron2Model.parse_aide_config(self.options, self.detectron2cfg)

        # #TODO: VERIFY: TridentNet seems to work with empty images
        # self.detectron2cfg.DATALOADER.FILTER_EMPTY_ANNOTATIONS = True



    @classmethod
    def getDefaultOptions(cls):
        return GenericDetectron2Model._load_default_options(
            'config/ai/model/detectron2/boundingBoxes/tridentnet.json',
            DEFAULT_OPTIONS
        )



    def _get_config(self):
        cfg = get_cfg()
        add_tridentnet_config(cfg)
        defaultConfig = optionsHelper.get_hierarchical_value(self.options, ['options', 'model', 'config', 'value', 'id'])
        configFile = os.path.join(os.getcwd(), 'ai/models/detectron2/_functional/configs', defaultConfig)
        cfg.merge_from_file(configFile)

        # disable SyncBatchNorm if not running on distributed system
        if comm.get_world_size() <= 1:
            cfg.MODEL.RESNETS.NORM = 'BN'
            cfg.MODEL.SEM_SEG_HEAD.NORM = 'BN'

        return cfg



    def loadAndAdaptModel(self, stateDict, data, updateStateFun):
        '''
            Loads a model and a labelclass map from a given "stateDict".
            First calls the parent implementation to obtain a default
            model, then checks for new label classes and modifies the
            model's classification head accordingly.
            TODO: implement advanced modifiers:
            1. Weighted linear combination of images with new annotations
               present
            2. Weighted linear combination according to similarity of name
               of new classes w.r.t. existing ones (e.g. using Word2Vec)
            
            For now, only the smallest existing class weights are used
            and duplicated.
            #TODO: 100% identical to Faster R-CNN routine
        '''
        model, stateDict, newClasses, projectToStateMap = self.initializeModel(stateDict, data)
        
        # modify model weights to accept new label classes
        if len(newClasses):

            # create temporary labelclassMap for new classes
            lcMap_new = dict(zip(newClasses, list(range(len(newClasses)))))

            # create vector of label classes
            classVector = len(stateDict['labelclassMap']) * [None]
            for (key, index) in zip(stateDict['labelclassMap'].keys(), stateDict['labelclassMap'].values()):
                classVector[index] = key

            # class predictor parameters
            class_weights = model.roi_heads.box_predictor.cls_score.weight
            class_biases = model.roi_heads.box_predictor.cls_score.bias

            # box predictor parameters
            bbox_weights = model.roi_heads.box_predictor.bbox_pred.weight
            bbox_biases = model.roi_heads.box_predictor.bbox_pred.bias


            # create weights and biases for new classes
            if True:        #TODO: add flags in config file about strategy
                class_weights_copy = class_weights.clone()
                class_biases_copy = class_biases.clone()
                bbox_weights_copy = bbox_weights.clone()
                bbox_biases_copy = bbox_biases.clone()

                modelClasses = range(len(class_biases))
                correlations = self.calculateClassCorrelations(stateDict, model, lcMap_new, modelClasses, newClasses, updateStateFun, 128)    #TODO: num images
                correlations = correlations[:,:-1].to(class_weights.device)      # exclude background class

                classMatches = (correlations.sum(1) > 0)            #TODO: calculate alternative strategies (e.g. class name similarities)

                randomIdx = torch.randperm(len(class_biases)-1)
                if len(randomIdx) < len(newClasses):
                    # source model has fewer classes than target model; repeat
                    randomIdx = randomIdx.repeat(int(len(newClasses)/len(class_biases)+1))

                for cl in range(len(newClasses)):

                    if classMatches[cl].item():
                        newClassWeight = class_weights_copy.clone()[:-1,:] * correlations[cl,:].unsqueeze(-1)
                        newClassBias = class_biases_copy.clone()[:-1] * correlations[cl,:]
                        newBoxWeight = bbox_weights_copy.clone() * correlations[cl,:].unsqueeze(-1).repeat(4,1)
                        newBoxBias = bbox_biases_copy.clone() * correlations[cl,:].repeat(4)

                        valid = (correlations[cl,:] > 0)

                        # average
                        newClassWeight = (newClassWeight.sum(0) / valid.sum()).unsqueeze(0)
                        newClassBias = newClassBias.sum() / valid.sum().unsqueeze(0)
                        newBoxWeight = newBoxWeight.view(-1, 4, bbox_weights_copy.size(-1)).sum(0) / valid.sum()
                        newBoxBias = newBoxBias.view(-1, 4).sum(0) / valid.sum()

                    else:
                        # class has no match; use alternative solution

                        #TODO: suboptimal alternative solution: choose random class
                        newClassWeight = class_weights_copy.clone()[randomIdx[cl],:].unsqueeze(0)
                        newClassBias = class_biases_copy.clone()[randomIdx[cl]].unsqueeze(0)
                        newBoxWeight = bbox_weights_copy.clone()[randomIdx[cl]*4:(randomIdx[cl]+1)*4,:]
                        newBoxBias = bbox_biases_copy.clone()[randomIdx[cl]*4:(randomIdx[cl]+1)*4]

                        # add a bit of noise
                        newClassWeight += (0.5 - torch.rand_like(newClassWeight)) * 0.5 * torch.std(class_weights_copy)
                        newClassBias += (0.5 - torch.rand_like(newClassBias)) * 0.5 * torch.std(class_biases_copy)
                        newBoxWeight += (0.5 - torch.rand_like(newBoxWeight)) * 0.5 * torch.std(bbox_weights_copy)
                        newBoxBias += (0.5 - torch.rand_like(newBoxBias)) * 0.5 * torch.std(bbox_biases_copy)

                    # prepend (last column is background class)
                    class_weights = torch.cat((newClassWeight, class_weights), 0)
                    class_biases = torch.cat((newClassBias, class_biases), 0)
                    bbox_weights = torch.cat((newBoxWeight, bbox_weights), 0)
                    bbox_biases = torch.cat((newBoxBias, bbox_biases), 0)
                    classVector.insert(0, newClasses[cl])

            # remove old classes
            classMap_updated = {}
            # valid_cls = torch.ones(len(class_biases), dtype=torch.bool)
            # valid_box = torch.ones(len(bbox_biases), dtype=torch.bool)
            index_updated = 0
            for idx, clName in enumerate(classVector):
                # if clName not in data['labelClasses']:
                #     valid_cls[idx] = 0
                #     valid_box[(idx*4):(idx+1)*4] = 0
                # else:
                if True:    # we don't remove old classes anymore (TODO: flag in configuration)
                    classMap_updated[clName] = index_updated
                    index_updated += 1
            
            # class_weights = class_weights[valid_cls,:]
            # class_biases = class_biases[valid_cls]
            # bbox_weights = bbox_weights[valid_box,:]
            # bbox_biases = bbox_biases[valid_box]

            # apply updated weights and biases
            model.roi_heads.box_predictor.cls_score.weight = torch.nn.Parameter(class_weights)
            model.roi_heads.box_predictor.cls_score.bias = torch.nn.Parameter(class_biases)

            model.roi_heads.box_predictor.bbox_pred.weight = torch.nn.Parameter(bbox_weights)
            model.roi_heads.box_predictor.bbox_pred.bias = torch.nn.Parameter(bbox_biases)

            stateDict['labelclassMap'] = classMap_updated

            print(f'[{self.project}] Neurons for {len(newClasses)} new label classes added to TridentNet model.')
        
        #TODO: remove superfluous?

        # finally, update model and config
        stateDict['detectron2cfg'].MODEL.ROI_HEADS.NUM_CLASSES = len(stateDict['labelclassMap'])
        model.roi_heads.box_predictor.cls_score.out_features = len(stateDict['labelclassMap'])
        model.roi_heads.box_predictor.bbox_pred.out_features = len(stateDict['labelclassMap'])
        return model, stateDict