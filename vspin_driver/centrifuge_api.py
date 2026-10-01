import serial
import time
import logging
import struct
from typing import Union, Optional

def crc16_xmodem(data: bytes) -> int:
    poly = 0x1021
    crc = 0x0000
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if (crc & 0x8000):
                crc = (crc << 1) ^ poly
            else:
                crc = (crc << 1)
    return crc & 0xFFFF

def build_loader_packet(opcode: int, payload: bytes) -> bytes:
    soh = b'\x11\x05\x00'
    total_length = len(payload) + 3
    total_length_bytes = struct.pack('<H', total_length)
    opcode_byte = struct.pack('<B', opcode)
    data_length_bytes = struct.pack('<H', len(payload))
    packet_base = soh + total_length_bytes + opcode_byte + data_length_bytes + payload
    crc = crc16_xmodem(packet_base)
    checksum_bytes = struct.pack('>H', crc)
    return packet_base + checksum_bytes

class LoaderNoPlateError(Exception):
    pass

class LoaderStageOccupiedError(Exception):
    pass

class VSpinCentrifuge:
    DOOR_STATUS = {
        "CLOSED": [b'\x00\x88\x0d\x00\x95', b'\x00\x08\x09\x00\x11'],
        "OPENING": [b'\x00\x88\x0f\x00\x97', b'\x00\x98\x0f\x00\xa7'],
        "OPEN": [b'\x00\xc8\x0f\x00\xd7'],
        "CLOSING": [b'\x00\xc8\x0d\x00\xd5'],
        "UNKNOWN": [None]
    }

    def __init__(self, port: str, calibration_offset: int):
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.timeout = 3.0
        self._is_initialized = False
        self.calibration_offset = calibration_offset
        self._bucket_1_position = 0
        self.homing_position = 0

    def connect(self, baudrate: int = 19200, rts: bool = False, dtr: bool = False):
        if self.ser.is_open: self.ser.close()
        self.ser.baudrate, self.ser.rts, self.ser.dtr = baudrate, rts, dtr
        self.ser.open()
        logging.info(f"Centrifuge: Successfully connected to {self.ser.port} at {self.ser.baudrate} baud.")

    def _write_command(self, command: Union[bytes, str], delay_after: float = 0.05):
        if isinstance(command, str): command = bytes.fromhex(command.replace(" ", ""))
        self.ser.write(command)
        time.sleep(delay_after)

    def _read_response(self) -> bytes:
        response = b""
        start_time = time.time()
        while time.time() - start_time < self.ser.timeout:
            if self.ser.in_waiting > 0:
                response += self.ser.read(self.ser.in_waiting)
            if response and response[-1] == 0x0D:
                break
            if response and len(response) >= 5 and response.startswith(b'\x00'):
                break
            time.sleep(0.01)
        return response

    def query(self, command: Union[bytes, str]) -> bytes:
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        self._write_command(command)
        return self._read_response()

    def initialize(self):
        if self._is_initialized:
            return

        logging.info("Starting centrifuge initialization...")
        self.connect(baudrate=19200)
        self._write_command(b'\x00' * 20)
        for i in range(33):
            packet = b"\xaa" + bytes([i & 0xFF, 0x0E, 0x0E + (i & 0xFF)]) + b"\x00" * 8
            self._write_command(packet, delay_after=0.02)
        self._write_command(b'\xaa\xff\x0f\x0e')

        self._write_command(b"\xaa\x00\x21\x01\xff\x21")
        self._write_command(b"\xaa\x01\x13\x20\x34")
        self._write_command(b"\xaa\x00\x21\x02\xff\x22")
        self._write_command(b"\xaa\x02\x13\x20\x35")
        self._write_command(b"\xaa\x00\x21\x03\xff\x23")
        self._write_command(b"\xaa\xff\x1a\x14\x2d")

        self.connect(baudrate=57600, rts=True, dtr=True)

        self._write_command(b"\xaa\x01\x0e\x0f")
        self._write_command(b"\xaa\x01\x12\x1f\x32")
        for _ in range(8):
            self._write_command(b"\xaa\x02\x20\xff\x0f\x30")
        self._write_command(b"\xaa\x02\x20\xdf\x0f\x10")
        self._write_command(b"\xaa\x02\x20\xdf\x0e\x0f")
        self._write_command(b"\xaa\x02\x20\xdf\x0c\x0d")
        self._write_command(b"\xaa\x02\x20\xdf\x08\x09")
        for _ in range(4):
            self._write_command(b"\xaa\x02\x26\x00\x00\x28")
        self._write_command(b"\xaa\x02\x12\x03\x17")
        for _ in range(5):
            self._write_command(b"\xaa\x02\x26\x20\x00\x48")
            self._write_command(b"\xaa\x02\x0e\x10")
            self._write_command(b"\xaa\x02\x26\x00\x00\x28")
            self._write_command(b"\xaa\x02\x0e\x10")
        self._write_command(b"\xaa\x02\x0e\x10")
        self.lock_door()

        for cmd_hex in ["aa010e0f", "aa020e10", "aa010e0f", "aa020e10", "aa010e0f", "aa020e10",
                        "aa020e10", "aa010e0f", "aa020e10", "aa0226000028", "aa020e10",
                        "aa020e10", "aa010e0f", "aa020e10"]:
            self._write_command(cmd_hex)

        for cmd_hex in ["aa0117021a", "aa010e0f", "aa01e6c800b00496000f004b00a00f050007",
                        "aa0117041c", "aa01170119", "aa010b0c", "aa010001",
                        "aa01e605006400000000003200e80301006e", "aa0194b61283000012010000f3",
                        "aa01192842", "aa010e0f"]:
            self._write_command(cmd_hex)

        self._rehome_after_spin()

        self._is_initialized = True
        logging.info("Centrifuge initialization complete.")

    def get_door_status(self) -> str:
        response = self.query(b'\xaa\x02\x0e\x10')
        for state, codes in self.DOOR_STATUS.items():
            if response in codes:
                if state == "IDLE_READY_CLOSED":
                    return "CLOSED"
                return state
        return "UNKNOWN"

    def open_door(self, timeout_s: int = 20):
        self._write_command(b"\xaa\x02\x26\x00\x07\x2F")
        self._write_command(b"\xaa\x02\x0e\x10")
        start_time = time.time()
        while time.time() - start_time < timeout_s:
            if self.get_door_status() == "OPEN":
                return
            time.sleep(1)
        raise TimeoutError("Timed out waiting for the door to open.")

    def close_door(self, timeout_s: int = 5):
        self._write_command(b"\xaa\x02\x26\x00\x05\x2d")
        self._write_command(b"\xaa\x02\x0e\x10")
        start_time = time.time()
        while time.time() - start_time < timeout_s:
            if self.get_door_status() == "CLOSED":
                return
            time.sleep(0.5)
        raise TimeoutError("Timed out waiting for the door to close.")

    def _get_position(self) -> Optional[int]:
        status = self.get_status()
        if status and len(status) >= 5:
            return int.from_bytes(status[1:5], byteorder="little")
        return None

    def _rehome_after_spin(self):
        while True:
            self._write_command(b"\xaa\x02\x0e\x10")
            stat = self.query(b"\xaa\x01\x0e\x0f")
            if not stat or stat[0] != 0x89:
                break
            time.sleep(0.1)

        for cmd_hex in ["aa010e0f", "aa010e0f", "aa0117021a", "aa010e0f",
                        "aa01e6c800b00496000f004b00a00f050007", "aa0117041c", "aa01170119",
                        "aa010b0c", "aa01e6c800b00496000f004b00a00f050007"]:
            self._write_command(cmd_hex)

        new_position = (self.homing_position + 8000).to_bytes(4, byteorder="little")
        self._write_command(b"\xaa\x01\xd4\x97" + new_position + b"\xc3\xf5\x28\x00\xd7\x1a\x00\x00\x49")
        self._write_command(b"\xaa\x01\x0e\x0f")
        self._write_command(b"\xaa\x01\x0e\x0f")

        while True:
            stat = self.query(b"\xaa\x01\x0e\x0f")
            self._write_command(b"\xaa\x01\x0e\x0f")
            if stat and stat[0] == 0x09:
                break
            time.sleep(0.2)

        self._write_command(b"\xaa\x01\x0e\x0f")
        self._write_command(b"\xaa\x01\x0e\x0f")
        self._write_command(b"\xaa\x01\x17\x02\x1a")
        self._write_command(b"\xaa\x02\x0e\x10")
        self.lock_door()
        self._write_command(b"\xaa\x01\x0e\x0f")

        home_pos = self._get_position()
        self._bucket_1_position = home_pos + self.calibration_offset

    def go_to_position(self, position: int):
        if not self._is_initialized: raise RuntimeError("Centrifuge is not initialized.")
        self.close_door()
        self.lock_door()

        pos_bytes = position.to_bytes(4, byteorder='little')
        cmd_base = b'\xaa\x01\xd4\x97' + pos_bytes + b'\xc3\xf5\x28\x00\xd7\x1a\x00\x00'
        checksum = (sum(cmd_base) - 0xAA) & 0xFF
        final_command = cmd_base + checksum.to_bytes(1, 'little')

        payload = [
            "aa0226000028", "aa020e10", "aa0117021a", "aa010e0f",
            "aa01e6c800b00496000f004b00a00f050007", "aa0117041c",
            "aa01170119", "aa010b0c", "aa01e6c800b00496000f004b00a00f050007"
        ]
        for cmd in payload: self._write_command(cmd)
        self._write_command(final_command)

        while True:
            status = self.get_status()
            if status and len(status) > 0:
                if status[0] != 0x08:
                    break
            time.sleep(2)

        self._write_command("aa0117021a")
        self.unlock_door()
        self.open_door()

    def go_to_bucket1(self): self.go_to_position(self._bucket_1_position)
    def go_to_bucket2(self): self.go_to_position(self._bucket_1_position + 4000)
    def lock_door(self): self._write_command(b"\xaa\x02\x26\x00\x01\x29"); self._write_command(b"\xaa\x02\x0e\x10")
    def unlock_door(self): self._write_command(b"\xaa\x02\x26\x00\x05\x2d"); self._write_command(b"\xaa\x02\x0e\x10")
    def unlock_bucket(self): self._write_command(b"\xaa\x02\x26\x00\x06\x2e"); self._write_command(b"\xaa\x02\x0e\x10")
    def get_status(self): return self.query(b"\xaa\x01\x0e\x0f")
    def lock_bucket(self): self._write_command(b"\xaa\x02\x26\x00\x07\x2f"); self._write_command(b"\xaa\x02\x0e\x10")

    def _reinitialize_for_shutdown(self):
        try:
            self.connect(baudrate=19200)
            self._write_command(b'\x00' * 20)
            for i in range(33):
                packet = b"\xaa" + bytes([i & 0xFF, 0x0E, 0x0E + (i & 0xFF)]) + b"\x00" * 8
                self._write_command(packet, delay_after=0.02)
            self.query(b'\xaa\xff\x0f\x0e')
        except Exception:
            pass

    def close(self):
        if not self.ser.is_open:
            return
        try:
            if self._is_initialized and self.ser.baudrate != 57600:
                self.connect(baudrate=57600, rts=True, dtr=True)
            if self._is_initialized:
                self._write_command(b"\xaa\x02\x0e\x10")
            self._reinitialize_for_shutdown()
            self._is_initialized = False
        finally:
            if self.ser.is_open:
                self.ser.close()

    def start_spin(self, g_force: float = 200, duration_s: int = 10, acceleration_percent: float = 40):
        if not self._is_initialized: raise RuntimeError("Centrifuge is not initialized.")
        self.close_door()
        self.lock_door()

        rpm = int((g_force / (1.118 * (10 ** -4))) ** 0.5)
        rpm_b = (int(4481 * rpm + 10852)).to_bytes(4, byteorder="little")
        acc_b = (int(915 * acceleration_percent / 100)).to_bytes(2, byteorder="little")
        current_pos = self._get_position()
        base = int(107007 - 328 * rpm + 1.13 * (rpm**2))
        max_pos = min((current_pos + base + 4000 * rpm // 30 * duration_s), 4294967294)
        pos_b = max_pos.to_bytes(4, byteorder="little")

        byte_string = b"\xaa\x01\xd4\x97" + pos_b + rpm_b + acc_b + b"\x00\x00"
        checksum = (sum(byte_string) - 0xAA) & 0xFF
        final_command = byte_string + checksum.to_bytes(1, "little")

        pre_spin_payloads = [
            "aa0226000028", "aa020e10", "aa0117021a", "aa010e0f",
            "aa01e6c800b00496000f004b00a00f050007", "aa0117041c",
            "aa01170119", "aa010b0c", "aa010e0f",
            "aa01e60500640000000000fd00803e01000c"
        ]
        for cmd in pre_spin_payloads: self._write_command(cmd)

        self._write_command(final_command)
        time.sleep(1)

        while True:
            status_resp = self.get_status()
            if status_resp and len(status_resp) > 0:
                if status_resp[0] == 0x08:
                    time.sleep(1)
                else:
                    break
            else:
                time.sleep(1)
        time.sleep(2)

        post_spin_payloads = [
            "aa01e6c800b00496000f004b00a00f050007", "aa0117041c", "aa01170119",
            "aa010b0c", "aa010001", "aa01e605006400000000003200e80301006e",
            "aa0194b61283000012010000f3", "aa01192842"
        ]
        for cmd in post_spin_payloads: self._write_command(cmd)
        self._rehome_after_spin()


class VSpinLoader:
    TEACHPOINT_ID = { "Park": 0, "Stage": 1, "Bucket 1": 2, "Bucket 2": 3, "Hover": 4 }
    SPEED = { "Slow": 0, "Medium": 1, "Fast": 2 }
    OPERATION_MODE = { "Static": 0, "Homing": 1, "Not Holding Plate": 2, "Holding Plate": 3 }

    OPTIONS_BITMASK = {
        "Ignore Plate Sensor": 0x01,
        "Grip Gently": 0x02
    }

    GRIPPER_Z_OFFSET_MIN = 2.6
    GRIPPER_Z_OFFSET_MAX = 21.1
    PLATE_HEIGHT_MIN = 2.6
    PLATE_HEIGHT_MAX = 48.3

    def __init__(self, port: str):
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.timeout = 5.0
        self._is_initialized = False

    def connect(self):
        if self.ser.is_open: self.ser.close()
        self.ser.baudrate = 115384
        self.ser.bytesize = serial.EIGHTBITS
        self.ser.parity = serial.PARITY_NONE
        self.ser.stopbits = serial.STOPBITS_ONE
        self.ser.open()
        logging.info(f"Loader: Successfully connected to {self.ser.port} at {self.ser.baudrate} baud.")

    def send_command(self, command: Union[bytes, str], delay_after: float = 0.05) -> bytes:
        if isinstance(command, str): command = bytes.fromhex(command.replace(" ", ""))
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        self.ser.write(command)
        time.sleep(delay_after)
        response = b""
        start_time = time.time()
        while (time.time() - start_time) < self.ser.timeout:
            if self.ser.in_waiting > 0:
                response += self.ser.read(self.ser.in_waiting)
            else:
                if response:
                    break
                time.sleep(0.05)
        return response

    def initialize(self):
        if self._is_initialized: return
        self.connect()
        init_payload = [
            "110500030014000072b1", "1105000300100000ae71", "110500070024040000008000be89",
            "11050007002404008000800063b1", "11050007002404000001800089b9",
            "1105000700240400800180005481", "110500070024040000024000c6bd",
            "1105000300400000f0bf", "1105000a004607000100000000020235bf",
            "11050003002000006bd4", "1105000e00440b00000000000000002041020203c7",
            "11050003002000006bd4"
        ]
        for cmd in init_payload: self.send_command(cmd)
        self._is_initialized = True

    def _open_gripper(self):
        packet = bytes.fromhex("1105000a0046070001000000000302068e")
        self.send_command(packet)
        time.sleep(0.5)

    def _close_gripper(self, is_gentle: bool):
        grip_mode_byte = 0x03 if is_gentle else 0x02
        payload = b'\x01\x00\x00\x80\x40' + struct.pack('<BB', grip_mode_byte, 0)
        packet = build_loader_packet(opcode=0x46, payload=payload)
        self.send_command(packet)
        time.sleep(0.5)

    def check_for_plate(self):
        check_command = bytes.fromhex("1105000300500000b3dc")
        response = self.send_command(check_command)
        no_plate_response = b"\x11\x05\x00\x08\x00Q\x05\x00\x00\x03\x00\x00\x00y\xf1"
        if response == no_plate_response:
            raise LoaderNoPlateError("Loader sensor check failed: No plate detected.")

    def check_stage_is_clear(self):
        check_command = bytes.fromhex("1105000300500000b3dc")
        response = self.send_command(check_command)
        no_plate_response = b"\x11\x05\x00\x08\x00Q\x05\x00\x00\x03\x00\x00\x00y\xf1"
        if response != no_plate_response:
            raise LoaderStageOccupiedError("Loader stage is occupied. Cannot proceed with unload.")

    def go_to_teachpoint(self, teachpoint_name: str, gripper_z_offset: float = 8.0, plate_height: float = 15.0, speed_name: str = "Fast", op_mode_name: str = "Not Holding Plate"):
        if not self._is_initialized: raise RuntimeError("Loader is not initialized.")
        tp_id = self.TEACHPOINT_ID[teachpoint_name]
        speed_id = self.SPEED[speed_name]
        op_mode_id = self.OPERATION_MODE[op_mode_name]

        payload = struct.pack('<BffBB', tp_id, gripper_z_offset, plate_height, op_mode_id, speed_id)
        packet = build_loader_packet(opcode=0x44, payload=payload)
        self.send_command(packet)

    def load(self, bucket_number: int, gripper_z_offset: float = 8.0, plate_height: float = 15.0, speed_name: str = "Fast", options: int = 0):
        if not self._is_initialized: raise RuntimeError("Loader is not initialized.")
        is_grip_gently = bool(options & self.OPTIONS_BITMASK["Grip Gently"])
        is_sensor_ignored = bool(options & self.OPTIONS_BITMASK["Ignore Plate Sensor"])

        try:
            self.go_to_teachpoint("Stage", gripper_z_offset, plate_height, speed_name, "Not Holding Plate")
            time.sleep(0.5)
            if not is_sensor_ignored:
                self.check_for_plate()
            self._close_gripper(is_gentle=is_grip_gently)
            self.go_to_teachpoint(f"Bucket {bucket_number}", gripper_z_offset, plate_height, speed_name, "Holding Plate")
            time.sleep(0.5)
            self._open_gripper()
            self.go_to_teachpoint("Park", gripper_z_offset, plate_height, speed_name, "Not Holding Plate")
        except Exception:
            self.go_to_teachpoint("Park")
            raise

    def unload(self, bucket_number: int, gripper_z_offset: float = 8.0, plate_height: float = 15.0, speed_name: str = "Fast", options: int = 0):
        if not self._is_initialized: raise RuntimeError("Loader is not initialized.")
        is_grip_gently = bool(options & self.OPTIONS_BITMASK["Grip Gently"])
        is_sensor_ignored = bool(options & self.OPTIONS_BITMASK["Ignore Plate Sensor"])

        try:
            self.go_to_teachpoint("Stage", gripper_z_offset, plate_height, speed_name, "Not Holding Plate")
            time.sleep(0.5)
            if not is_sensor_ignored:
                self.check_stage_is_clear()
            self.go_to_teachpoint(f"Bucket {bucket_number}", gripper_z_offset, plate_height, speed_name, "Not Holding Plate")
            time.sleep(0.5)
            if not is_sensor_ignored:
                self.check_for_plate()
            self._close_gripper(is_gentle=is_grip_gently)
            self.go_to_teachpoint("Stage", gripper_z_offset, plate_height, speed_name, "Holding Plate")
            time.sleep(0.5)
            self._open_gripper()
            self.go_to_teachpoint("Park", gripper_z_offset, plate_height, speed_name, "Not Holding Plate")
        except Exception:
            self.go_to_teachpoint("Park")
            raise

    def close(self):
        if self.ser.is_open:
            self.ser.close()
        self._is_initialized = False