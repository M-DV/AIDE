'''
    Detectron2-compliant wrapper for DeepForest models:
    https://github.com/weecology/DeepForest

    2022-24 Benjamin Kellenberger
'''

import torch
from torch import nn
from torchvision.models.detection import (retinanet_resnet50_fpn,
                                          RetinaNet_ResNet50_FPN_Weights)
from detectron2.modeling import (build_backbone,
                                 BACKBONE_REGISTRY,
                                 META_ARCH_REGISTRY,
                                 Backbone,
                                 ShapeSpec)
from detectron2.structures import Instances, Boxes
from deepforest.main import deepforest
from deepforest import utilities
# from deepforest.model import load_backbone, create_anchor_generator, create_model


# @BACKBONE_REGISTRY.register()
# class DeepForestBackbone(Backbone):

#     def __init__(self, cfg, input_shape={}):
#         super(DeepForestBackbone, self).__init__()
#         self.backbone = retinanet_resnet50_fpn(weights=RetinaNet_ResNet50_FPN_Weights.COCO_V1)
#         self.out_channels = self.backbone.backbone.out_channels

#     def forward(self, x):
#         return {'out': self.backbone(x)}
    
#     def output_shape(self):
#         # not needed since our DeepForest (below) is hard-coded, but here for
#         # completeness
#         return {
#             'out': ShapeSpec(channels=2048, stride=1)   #TODO
#         }



@META_ARCH_REGISTRY.register()
class DeepForest(nn.Module):
    '''
        Detectron2-compliant wrapper for DeepForest (RetinaNet).
    '''
    def __init__(self, cfg):
        super().__init__()

        # load pre-trained DeepForest model if available
        num_classes = cfg.MODEL.RETINANET.NUM_CLASSES

        self.release_state_dict = None
        pretrained_name = cfg.MODEL.DEEPFOREST_PRETRAINED
        if pretrained_name == 'deepforest':
            _, self.release_state_dict = utilities.use_release(check_release=True)
            num_classes = 1
            # self.names = ('tree',)
            label_dict = {'Tree': 0}
        elif pretrained_name == 'birddetector':
            _, self.release_state_dict = utilities.use_bird_release(check_release=True)
            num_classes = 1
            # self.names = ('bird',)
            label_dict = {'Bird': 0}

        if len(cfg.get('LABELCLASS_MAP', {})) > 0:
            label_dict = dict(cfg['LABELCLASS_MAP'])
        self.model = deepforest(
            label_dict=label_dict,
            config_args={
                'num_classes': num_classes,
                'nms_thresh': cfg.MODEL.RETINANET.NMS_THRESH_TEST,
                'retinanet': {
                    'score_thresh': cfg.MODEL.RETINANET.SCORE_THRESH_TEST
                }
            }
        )

        if self.release_state_dict is not None:
            self.model.model.load_state_dict(
                torch.load(self.release_state_dict, map_location='cpu'), strict=False)

        self.out_channels = self.model.model.backbone.out_channels

    @property
    def device(self) -> torch.device:
        '''
            Returns the model's compute device (torch.device)
        '''
        return self.model.model.head.classification_head.cls_logits.weight.device

    @property
    def dtype(self):
        '''
            Returns the number type the model uses
        '''
        return self.model.model.head.classification_head.cls_logits.weight.dtype

    def forward(self, inputs):
        '''
            Model forward pass.
        '''
        images = [i['image'].float().to(self.device)/255 for i in inputs]
        targets = None
        if self.training:
            targets = []
            for i in inputs:
                if 'instances' in i:
                    targets.append({
                        'boxes': i['instances'].gt_boxes.tensor.to(self.device),
                        'labels': i['instances'].gt_classes.long().to(self.device)
                    })
                else:
                    targets.append({
                        'boxes': torch.empty((0, 4,), dtype=torch.float32, device=self.device),
                        'labels': torch.empty((0,), dtype=torch.long, device=self.device)
                    })

        if self.training:
            return self.model.model(images, targets)

        # prediction
        out = self.model.model(images)
        if len(out[0]['labels']) > 0:
            instances = Instances(image_size=(images[0].size(1), images[0].size(2)))
            instances.pred_classes = out[0]['labels']
            instances.pred_boxes = Boxes(out[0]['boxes'][:,:4])
            instances.scores = out[0]['scores']
            return [{'instances': instances}]
        else:
            return [{}]
