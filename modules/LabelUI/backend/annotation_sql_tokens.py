'''
    Contains SQL fragments for retrieval and submission of data
    for each of the annotation types.

    2019 Benjamin Kellenberger
'''

#BIG TODO: MERGE WITH sql_string_builder.py

from enum import Enum
from uuid import UUID



class QueryStrings_prediction(Enum):
    labels = ['id', 'image', 'label', 'confidence', 'priority'],
    points = ['id', 'image', 'x', 'y', 'label', 'confidence', 'priority'],
    boundingBoxes = ['id', 'image', 'x', 'y', 'width', 'height', 'label', 'confidence', 'priority'],
    segmentationMasks = ['id', 'image', 'filename', 'priority']


class QueryStrings_annotation(Enum):
    labels = ['id', 'image', 'label', 'username', 'timeCreated', 'timeRequired', 'unsure'],
    points = ['id', 'image', 'x', 'y', 'label', 'username', 'timeCreated', 'timeRequired', 'unsure'],
    boundingBoxes = ['id', 'image', 'x', 'y', 'width', 'height', 'label', 'username', 'timeCreated', 'timeRequired', 'unsure'],
    segmentationMasks = ['id', 'image', 'filename', 'username', 'timeCreated', 'timeRequired', 'unsure']




class AnnotationParser:

    def __init__(self, config):
        # for bounding boxes
        self.minWidth = config.getProperty('Project', 'box_minWidth', type=int, fallback=1)
        self.minHeight = config.getProperty('Project', 'box_minHeight', type=int, fallback=1)


    def parseAnnotation(self, annotation):
        '''
            Receives an annotation object as submitted by the labeling UI.
            Returns a dictionary of column names and values.
        '''
        valuesDict = {}

        for key in annotation.keys():
            if key == 'id':
                # check if new annotation (non-UUID conformant ID)
                # or update for existing
                try:
                    value = str(UUID(annotation['id']))
                except:
                    # non-UUID conformant ID: skip 'id' field
                    continue
            
            elif key == 'geometry':
                # iterate through geometry tokens
                for subKey in annotation['geometry'].keys():
                    valuesDict[subKey] = annotation['geometry'][subKey]
                continue
            
            else:
                # generic parameter
                value = annotation[key]
        
            valuesDict[key] = value

        return valuesDict