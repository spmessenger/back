from pydantic import BaseModel


class AvatarUpload(BaseModel):
    data_url: str
    stage_size: float
    crop_x: float
    crop_y: float
    crop_size: float
