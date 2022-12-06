'''
    PyTorch dataset wrapper for segmentation masks.

    2020-21 Benjamin Kellenberger
'''

from io import BytesIO
import numpy as np
import base64
from PIL import Image
from torch.utils.data import Dataset


class SegmentationDataset(Dataset):
    '''
        #TODO: update description
        PyTorch-conform wrapper for a dataset containing bounding boxes.
        Inputs:
        - data:     A dict with the following entries:
                    - labelClasses: dict with { <labelclass UUID> : { 'index' (labelClass index for this CNN) }}
                    - images: dict with
                              { <image UUID> : { 'annotations' : { <annotation UUID> : { 'segmentationmask', 'width', 'height' }}}}
                    - 'fVec': optional, contains feature vector bytes for image
        - fileServer: Instance that implements a 'getFile' function to load images
        - labelclassMap: a dictionary/LUT with mapping: key = label class UUID, value = index (number) according
                         to the model.
        - transform: Instance of classes defined in 'ai.models.pytorch.functional.transforms.segmentationMasks'. May be None for no transformation at all.

        The '__getitem__' function returns the data entry at given index as a tuple with the following contents:
        - img: the loaded and transformed (if specified) image.
        - segmentationMask: the loaded and transformed (if specified) segmentation mask.
        - imageID: str, filename of the image loaded
    '''
    def __init__(self, data, fileServer, labelclassMap, transform=None, **kwargs):
        super(SegmentationDataset, self).__init__()
        self.data = data
        self.fileServer = fileServer
        self.labelclassMap = labelclassMap
        self.transform = transform
        self.imageOrder = list(self.data['images'].keys())
        self.ignore_unlabeled = (kwargs['ignore_unlabeled'] if 'ignore_unlabeled' in kwargs else True)
        self.indexMap = (kwargs['index_map'] if 'index_map' in kwargs else None)


    def __len__(self):
        return len(self.imageOrder)

    
    def __getitem__(self, idx):
        imageID = self.imageOrder[idx]
        dataDesc = self.data['images'][imageID]

        # load image
        imagePath = dataDesc['filename']
        try:
            img = Image.open(BytesIO(self.fileServer.getFile(imagePath))).convert('RGB')
            imageSize = img.size
        except Exception:
            print(f'WARNING: Image "{imagePath}" is corrupt and could not be loaded.')
            img = None
            imageSize = None
        
        # load and decode segmentation mask
        if 'annotations' in dataDesc and len(dataDesc['annotations']):
            annotation = dataDesc['annotations'][0]
            try:
                width = int(annotation['width'])
                height = int(annotation['height'])
                raster = np.frombuffer(base64.b64decode(annotation['segmentationmask']), dtype=np.uint8)
                raster = np.reshape(raster, (height,width,))

                if self.indexMap is not None:
                    # map from AIDE to model class indices
                    raster_copy = np.copy(raster)
                    for k, v in self.classIndexMap.items(): raster_copy[raster==k] = v
                    raster = raster_copy

                segmentationMask = Image.fromarray(raster)

            except Exception:
                print(f'WARNING: Segmentation mask for image "{imagePath}" could not be loaded or decoded.')
                segmentationMask = None
        else:
            segmentationMask = None
        
        if self.transform is not None and img is not None:
            img, segmentationMask = self.transform(img, segmentationMask)
        
        if segmentationMask is not None:
            if self.ignore_unlabeled:
                # no dedicated background class; shift all indices down
                segmentationMask = (segmentationMask - 1).clamp(0)

        return img, segmentationMask, imageSize, imageID
