'''
    Utilities to load images of various formats.

    2021-22 Benjamin Kellenberger
'''

import mimetypes
mimetypes.init()

from io import BytesIO
import numpy as np


def bytea_to_bytesio(bytea):
    '''
        Returns a BytesIO wrapper around a given byte array (or the object
        itself if it already is a BytesIO instance).
        TODO: double definition, also in __init__ file...
    '''
    if isinstance(bytea, BytesIO):
        bytea.seek(0)
        return bytea
    else:
        bytesIO = BytesIO(bytea)
        bytesIO.seek(0)
        return bytesIO



def bytesio_to_bytea(bytesio):
    '''
        Returns a byte array from a BytesIO wrapper.
    '''
    if isinstance(bytesio, BytesIO):
        bytesio.seek(0)
        return bytesio.getvalue()
    else:
        return bytesio



def normalize_image(img, band_axis=0, color_range=255):
    '''
        Receives an image in np.array format and normalizes it into a [0, 255]
        uint8 image. Parameter "band_axis" determines in which axis the image
        bands can be found. Parameter "color_range" defines the maximum
        obtainable integer value per band. Default is 255 (full uint8 range),
        but lower values may be specified to e.g. perform a crude quantization
        of the image color space.
    '''
    if img.ndim == 2:
        img = img[np.newaxis,...]
        band_axis = 0
    if not isinstance(color_range, int) and not isinstance(color_range, float):
        color_range = 255
    else:
        color_range = int(min(255, max(0, color_range)))
    permuted = False
    if band_axis != 0:
        permuted = True
        if band_axis < 0:
            band_axis = img.ndim + band_axis
        bOrder = list(range(img.ndim))
        bOrder.remove(band_axis)
        bOrder.insert(0,band_axis)
        img = np.transpose(img, (bOrder))
    sz = img.shape
    img = img.reshape((sz[0], -1)).astype(np.float32)
    mins = np.min(img, 1)[:,np.newaxis]
    maxs = np.max(img, 1)[:,np.newaxis]
    img = (img - mins)/(maxs - mins)
    img = color_range * img.reshape(sz)
    if permuted:
        # permute back
        img = np.transpose(img, np.argsort(bOrder))
    img = img.astype(np.uint8)
    return img




class AbstractImageDriver:
    '''
        Abstract base class for image drivers. Convention: all drivers must
        return a NumPy ndarray of size (BxWxH), even if B=1. The number type or
        pixel values must not be changed from the original.
    '''

    NAME = 'abstract'
    PRIORITY = -1

    SUPPORTED_MEDIA_TYPES = ('image')

    SUPPORTED_EXTENSIONS = ()
    MULTIBAND_SUPPORTED = False

    @classmethod
    def init_is_available(cls):
        return False
    
    @classmethod
    def is_loadable(cls, object):
        return False

    @classmethod
    def size(cls, object):
        raise NotImplementedError('Not implemented for abstract base class.')

    @classmethod
    def load(cls, object, **kwargs):
        if isinstance(object, str):
            return cls.load_from_disk(object, **kwargs)
        else:
            return cls.load_from_bytes(object, **kwargs)

    @classmethod
    def load_from_disk(cls, filePath, **kwargs):
        raise NotImplementedError('Not implemented for abstract base class.')
    
    @classmethod
    def load_from_bytes(cls, bytea, **kwargs):
        raise NotImplementedError('Not implemented for abstract base class.')
    
    @classmethod
    def save_to_disk(cls, array, filePath, **kwargs):
        raise NotImplementedError('Not implemented for abstract base class.')
    
    @classmethod
    def save_to_bytes(cls, array, format, **kwargs):
        raise NotImplementedError('Not implemented for abstract base class.')
    
    @classmethod
    def disk_to_bytes(cls, filePath, **kwargs):
        raise NotImplementedError('Not implemented for abstract base class.')

    @classmethod
    def get_supported_extensions(cls):
        return cls.SUPPORTED_EXTENSIONS

    @classmethod
    def get_supported_mime_types(cls):
        return [mimetypes.types_map[s] for s in cls.SUPPORTED_EXTENSIONS if s in mimetypes.types_map]



class PILImageDriver(AbstractImageDriver):
    '''
        Uses the Python Image Library to load images. Fallback for when others
        (GDALImageDriver, etc.) don't work, as this one is limited to RGB data.
    '''

    NAME = 'PIL'
    PRIORITY = 10

    SUPPORTED_EXTENSIONS = (
        '.bmp',
        '.gif',
        '.icns',
        '.ico',
        '.jpg', '.jpeg',
        '.jp2', '.j2k',
        '.tif', '.tiff',
        '.webp'
    )

    @classmethod
    def init_is_available(cls):
        from PIL import Image
        cls.loader = Image
        return True

    @classmethod
    def is_loadable(cls, object):
        img = None
        try:
            if isinstance(object, str):
                img = cls.loader.open(object)
            else:
                img = cls.loader.open(bytea_to_bytesio(object))
            img.verify()
            img.close()     #TODO: needed?
            return True
        except:
            return False
        finally:
            if hasattr(img, 'close'):
                img.close()
    
    @classmethod
    def size(cls, object):
        if isinstance(object, str):
            img = cls.loader.open(object)
        else:
            img = cls.loader.open(bytea_to_bytesio(object))
        sz = [len(img.getbands()), img.height, img.width]
        img.close()
        return sz

    @classmethod
    def load_from_disk(cls, filePath, **kwargs):
        img = cls.loader.open(filePath)
        if 'window' in kwargs and kwargs['window'] is not None:
            # crop
            img = img.crop(*kwargs['window'])
        arr = np.array(img)
        if arr.ndim == 2:
            return arr[np.newaxis,...]
        else:
            return arr.transpose((2,0,1))
    
    @classmethod
    def load_from_bytes(cls, bytea, **kwargs):
        img = cls.loader.open(bytea_to_bytesio(bytea))
        if 'window' in kwargs and kwargs['window'] is not None:
            # crop
            img = img.crop(*kwargs['window'])
        arr = np.array(img)
        if arr.ndim == 2:
            return arr[np.newaxis,...]
        else:
            return arr.transpose((2,0,1))
    
    @classmethod
    def save_to_disk(cls, array, filePath, **kwargs):
        img = cls.loader.fromarray(array)
        img.save(filePath)
    
    @classmethod
    def save_to_bytes(cls, array, format, **kwargs):
        bio = BytesIO()
        img = cls.loader.fromarray(array)
        img.save(bio, format=format)
        return bio
    
    @classmethod
    def disk_to_bytes(cls, filePath, **kwargs):
        img = cls.loader.open(filePath)
        if 'window' in kwargs:
            # crop
            img = img.crop(*kwargs['window'])
        bio = BytesIO()
        img.save(bio, format=img.format)
        return bio
        


class GDALImageDriver(AbstractImageDriver):
    '''
        Uses GDAL via the rasterio bindings to load images.
    '''

    NAME = 'GDAL'
    PRIORITY = 20

    #TODO: list currently incomplete; see https://gdal.org/drivers/raster/index.html
    SUPPORTED_EXTENSIONS = (
        '.bmp',
        '.gif',
        '.gff',
        '.gpkg',
        '.grd',
        '.heic',
        '.img',
        '.jpg', '.jpeg',
        '.jp2', '.j2k',
        '.nc',
        '.ntf',
        '.pdf',
        '.png',
        '.tif', '.tiff',
        '.webp'
    )

    @classmethod
    def init_is_available(cls):
        import rasterio
        cls.driver = rasterio
        from rasterio.io import MemoryFile
        cls.memfile = MemoryFile
        from rasterio.windows import Window
        cls.window = Window

        # filter "NotGeoreferencedWarning"      #TODO: test
        import warnings
        warnings.filterwarnings("ignore", category=rasterio.errors.NotGeoreferencedWarning)
        return True
    
    @classmethod
    def is_loadable(cls, object):
        try:
            if isinstance(object, str):
                with cls.driver.open(object, 'r'):
                    valid = True    #TODO
            else:
                with cls.memfile(bytesio_to_bytea(object)) as memfile:
                    with memfile.open():
                        valid = True
            return valid
        except:
            return False
    
    @classmethod
    def size(cls, object):
        if isinstance(object, str):
            with cls.driver.open(object, 'r') as f:
                sz = [f.count, f.height, f.width]
        else:
            with cls.memfile(bytesio_to_bytea(object)) as memfile:
                with memfile.open() as f:
                    sz = [f.count, f.height, f.width]
        return sz
    
    @classmethod
    def load_from_disk(cls, filePath, **kwargs):
        if 'window' in kwargs and kwargs['window'] is not None:
            # crop
            window = cls.window(*kwargs['window'])
        else:
            window = None
        with cls.driver.open(filePath, 'r') as f:
            raster = f.read(window=window, boundless=True)
        return raster
    
    @classmethod
    def load_from_bytes(cls, bytea, **kwargs):
        if 'window' in kwargs and kwargs['window'] is not None:
            # crop
            window = cls.window(*kwargs['window'])
        else:
            window = None
        with cls.memfile(bytesio_to_bytea(bytea)) as memfile:
            with memfile.open() as f:
                raster = f.read(window=window, boundless=True)
        return raster

    @classmethod
    def save_to_disk(cls, array, filePath, **kwargs):
        if isinstance(kwargs, dict):
            out_meta = kwargs
        else:
            out_meta = {}
        if 'width' not in out_meta:
            out_meta['width'] = array.shape[2]
        if 'height' not in out_meta:
            out_meta['height'] = array.shape[1]
        if 'count' not in out_meta:
            out_meta['count'] = array.shape[0]
        if 'dtype' not in out_meta:
            out_meta['dtype'] = str(array.dtype)
        if 'transform' not in out_meta:
            # add identity transform to suppress "NotGeoreferencedWarning"
            out_meta['transform'] = cls.driver.Affine.identity()
        with cls.driver.open(filePath, 'w', **out_meta) as dest_img:
            dest_img.write(array)

    @classmethod
    def save_to_bytes(cls, array, format, **kwargs):        #TODO: format
        if isinstance(kwargs, dict):
            out_meta = kwargs
        else:
            out_meta = {}
        if 'width' not in out_meta:
            out_meta['width'] = array.shape[2]
        if 'height' not in out_meta:
            out_meta['height'] = array.shape[1]
        if 'count' not in out_meta:
            out_meta['count'] = array.shape[0]
        if 'dtype' not in out_meta:
            out_meta['dtype'] = str(array.dtype)
        if 'transform' not in out_meta:
            # add identity transform to suppress "NotGeoreferencedWarning"
            out_meta['transform'] = cls.driver.Affine.identity()
        with cls.memfile() as memfile:
            memfile.write(array)
        return memfile
    
    @classmethod
    def disk_to_bytes(cls, filePath, **kwargs):
        if 'window' in kwargs and kwargs['window'] is not None:
            # crop
            window = cls.window(*kwargs['window'])
        else:
            window = None
        with cls.driver.open(filePath, 'r') as f:
            data = f.read(window=window, boundless=True)
            profile = f.profile
        if window is not None:
            profile['width'] = window.width
            profile['height'] = window.height

        with cls.memfile() as memfile:
            with memfile.open(**profile) as rst:
                rst.write(data)
            memfile.seek(0)
            bytes = memfile.read()
        return bytes



class DICOMImageDriver(AbstractImageDriver):
    '''
        Driver for DICOM files using pyDICOM.
    '''

    NAME = 'DICOM'
    PRIORITY = 5

    SUPPORTED_EXTENSIONS = (
        '.dcm',
    )

    @classmethod
    def init_is_available(cls):
        from pydicom import dcmread
        cls.loader = dcmread
        return True
    
    @classmethod
    def is_loadable(cls, object):
        #TODO: check if optimizable
        try:
            if isinstance(object, str):
                img = cls.load_from_disk(object)
            else:
                img = cls.load_from_bytes(object)
            return isinstance(img, np.ndarray)
        except:
            return False
    
    @classmethod
    def size(cls, object):
        #TODO: check if optimizable
        if isinstance(object, str):
            img = cls.load_from_disk(object)
        else:
            img = cls.load_from_bytes(object)
        return list(img.shape)

    @classmethod
    def load_from_disk(cls, filePath, **kwargs):
        data = cls.loader(filePath)
        raster = data.pixel_array
        if raster.ndim == 2:
            raster = raster[np.newaxis,...]
        return raster
    
    @classmethod
    def load_from_bytes(cls, bytea, **kwargs):
        bytesIO = bytea_to_bytesio(bytea)
        data = cls.loader(bytesIO)
        raster = data.pixel_array
        if raster.ndim == 2:
            raster = raster[np.newaxis,...]
        return raster
    
    @classmethod
    def save_to_disk(cls, array, filePath, **kwargs):
        raise NotImplementedError('TODO: not yet implemented for DICOM parser.')


if __name__ == '__main__':
    drivers = (
        PILImageDriver,
        GDALImageDriver,
        DICOMImageDriver
    )

    for driver in drivers:
        dname = driver.NAME
        try:
            if not driver.init_is_available():
                raise Exception('driver not available')
            else:
                print(f'Driver "{dname}" initialized.')
        except Exception as e:
            print(f'Driver "{dname}" unavailable ("{str(e)}")')