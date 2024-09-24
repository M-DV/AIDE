'''
    HerdNet specifier for Detectron2 model trainer in AIDE:
    https://github.com/Alexandre-Delplanque/HerdNet

    2024 Benjamin Kellenberger
'''

import os
import torch
from detectron2.config import get_cfg
from ai.models.detectron2.genericDetectronModel import GenericDetectron2Model
from ai.models.detectron2.boundingBoxes.genericDetectronBBoxModel import \
    GenericDetectron2BoundingBoxModel
from ai.models.detectron2.boundingBoxes.herdnet import DEFAULT_OPTIONS
from util import optionsHelper



class HerdNet(GenericDetectron2BoundingBoxModel):
    '''
        Detectron2-compliant wrapper for HerdNet.
    '''
    def __init__(self,
                 project: str,
                 config: dict,
                 dbConnector,
                 fileServer,
                 options: dict) -> None:
        super().__init__(project,
                         config,
                         dbConnector,
                         fileServer,
                         options)

        try:
            if self.detectron2cfg.MODEL.META_ARCHITECTURE != 'HerdNet':
                # invalid options provided
                raise Exception('Invalid model architecture')
        except Exception:
            print('WARNING: provided options are not valid for HerdNet; falling back to defaults.')
            self.options = self.getDefaultOptions()
            self.detectron2cfg = self._get_config()
            self.detectron2cfg = GenericDetectron2Model.parse_aide_config(self.options,
                                                                          self.detectron2cfg)


    @classmethod
    def getDefaultOptions(cls):
        return GenericDetectron2Model._load_default_options(
            'config/ai/model/detectron2/boundingBoxes/herdnet.json',
            DEFAULT_OPTIONS
        )