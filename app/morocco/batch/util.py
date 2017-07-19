from typing import List, Union
from azure.batch.models import MetadataItem


def get_metadata(metadata: List[MetadataItem], name: str) -> Union[str, None]:
    for each in metadata or []:
        if each.name == name:
            return each.value
    return None
