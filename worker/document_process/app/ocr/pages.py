"""The image of a page, handed from the extraction worker to the OCR pods through S3.

Never through Redis: a Celery message only carries a key and small JSON. The images are temporary - dropped when
the extraction of the document ends, whichever way it ends - and apart from `screenshots/`, which stay."""

PAGE_IMAGES_PREFIX = "ocr-pages/"


def page_images_prefix(document_id: str) -> str:
    return f"{PAGE_IMAGES_PREFIX}{document_id}/"


def page_image_key(document_id: str, page_number: int) -> str:
    return f"{page_images_prefix(document_id)}page-{page_number}.png"


def put_page_image(storage, document_id: str, page_number: int, image_bytes: bytes) -> str:
    """Stores the image of a page and gives its key."""
    key = page_image_key(document_id, page_number)
    storage.put_object(key, image_bytes, content_type="image/png")
    return key


def get_page_image(storage, key: str) -> bytes:
    return storage.get_object(key)


def delete_page_images(storage, document_id: str) -> int:
    """Drops every temporary image of a document; gives how many there were."""
    return storage.delete_prefix(page_images_prefix(document_id))


def delete_pages_images(storage, document_id: str, page_numbers: list[int]) -> None:
    """Drops the temporary images of some pages of a document - the ranges of a long PDF are read at the same time,
    each only drops its own."""
    storage.delete_objects([page_image_key(document_id, number) for number in page_numbers])
