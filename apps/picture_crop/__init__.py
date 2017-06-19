
import superdesk

from flask import current_app as app, json
from superdesk.utils import get_random_string
from superdesk.media.media_operations import crop_image, process_image, encode_metadata
from apps.search_providers.proxy import PROXY_ENDPOINT
from superdesk.media.image import fix_orientation


def get_file(rendition, item):
    if item.get('fetch_endpoint'):
        if item['fetch_endpoint'] == PROXY_ENDPOINT:  # it requires provider info
            return superdesk.get_resource_service(item['fetch_endpoint']).fetch_rendition(rendition, item=item)
        return superdesk.get_resource_service(item['fetch_endpoint']).fetch_rendition(rendition)
    else:
        return app.media.fetch_rendition(rendition)


def get_crop_size(crop):
    """In case width or height is missing it will do the math.

    :param size: size dict with `width` or `height`
    :param crop: crop specs
    """
    crop_width = crop['CropRight'] - crop['CropLeft']
    crop_height = crop['CropBottom'] - crop['CropTop']

    size = {
        'width': crop.get('width', crop_width),
        'height': crop.get('height', crop_height)
    }

    crop_ratio = crop_height / crop_width
    size_ratio = size['height'] / size['width']

    # Keep crop data proportional to the size provided
    # i.e. if the rendition is 4x3, make sure the crop data is also a 4x3 aspect ratio
    if crop_ratio != size_ratio:
        crop_width = int(crop_height / size_ratio)
        crop_height = int(crop_width * size_ratio)

        # Calculating from the top-left, re-assign the cropping coordinates
        # based on the new aspect ratio of the crop
        crop['CropRight'] = crop['CropLeft'] + crop_width
        crop['CropBottom'] = crop['CropTop'] + crop_height

    return size


class PictureCropService(superdesk.Service):
    """Crop original image of picture item and return its url.

    It is used for embedded images within text item body.
    """

    def create(self, docs, **kwargs):
        ids = []
        for doc in docs:
            item = doc.pop('item')
            crop = doc.pop('crop')
            size = get_crop_size(crop)
            orig = item['renditions']['original']
            orig_file = get_file(orig, item)
            filename = get_random_string()
            ok, output = crop_image(orig_file, filename, crop, size)
            if ok:
                metadata = encode_metadata(process_image(orig_file))
                metadata.update({'length': json.dumps(len(output.getvalue()))})
                output = fix_orientation(output)
                media = app.media.put(output, filename, orig['mimetype'], metadata=metadata)
                doc['href'] = app.media.url_for_media(media, orig['mimetype'])
                doc['width'] = output.width
                doc['height'] = output.height
                ids.append(media)
        return ids


class PictureCropResource(superdesk.Resource):

    item_methods = []
    resource_methods = ['POST']
    privileges = {'POST': 'archive'}

    schema = {
        'item': {'type': 'dict', 'required': True},
        'crop': {'type': 'dict', 'required': True}
    }


def init_app(app):
    superdesk.register_resource(
        'picture_crop',
        PictureCropResource,
        PictureCropService,
        'archive')
