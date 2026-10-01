from typing import Optional
from uuid import UUID, uuid4

from sila2.server import SilaServer

from .feature_implementations.vspincontroller_impl import VSpinControllerImpl
from .generated.vspincontroller import VSpinControllerFeature

class Server(SilaServer):
    def __init__(
        self,
        server_uuid: Optional[UUID] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        centrifuge_com_port: str = "COM15",
        loader_com_port: str = "COM13",
        calibration_offset: int = 5198,
    ):
        if name is None:
            name = "VSpin Server"
        if description is None:
            description = "A SiLA 2 Server for the Agilent VSpin Centrifuge and Loader"

        super().__init__(
            server_name=name,
            server_description=description,
            server_type="VSpin",
            server_version="1.0",
            server_vendor_url="https://github.com/SiLA2/sila_python",
            server_uuid=server_uuid if server_uuid is not None else uuid4(),
        )

        self.centrifuge_com_port = centrifuge_com_port
        self.loader_com_port = loader_com_port
        self.calibration_offset = calibration_offset

        self.vspincontroller = VSpinControllerImpl(self)
        self.set_feature_implementation(VSpinControllerFeature, self.vspincontroller)