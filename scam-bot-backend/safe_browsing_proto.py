"""โครงสร้างคำตอบ urls.search V5 และการแปลง Protobuf เป็น dict.

อ้างอิง: https://developers.google.com/safe-browsing/reference/rpc/google.security.safebrowsing.v5
"""
from google.protobuf import descriptor_pool, duration_pb2, message_factory
from google.protobuf.descriptor_pb2 import FieldDescriptorProto, FileDescriptorProto
from google.protobuf.json_format import MessageToDict, SerializeToJsonError
from google.protobuf.message import DecodeError


# เลขฟิลด์และเลข enum เป็นส่วนหนึ่งของ protocol ไม่ใช่ลำดับสำหรับแสดงผล
_schema = FileDescriptorProto(
    name="linebot_safe_browsing.proto",
    package="linebot.safe_browsing",
    syntax="proto3",
    dependency=["google/protobuf/duration.proto"],
)
_threat_type = _schema.enum_type.add(name="ThreatType", value=[
    {"name": "THREAT_TYPE_UNSPECIFIED", "number": 0},
    {"name": "MALWARE", "number": 1},
    {"name": "SOCIAL_ENGINEERING", "number": 2},
    {"name": "UNWANTED_SOFTWARE", "number": 3},
    {"name": "POTENTIALLY_HARMFUL_APPLICATION", "number": 4},
])
_schema.message_type.add(name="ThreatUrl", field=[
    {
        "name": "url", "number": 1,
        "label": FieldDescriptorProto.LABEL_OPTIONAL,
        "type": FieldDescriptorProto.TYPE_STRING,
    },
    {
        "name": "threat_types", "number": 2,
        "label": FieldDescriptorProto.LABEL_REPEATED,
        "type": FieldDescriptorProto.TYPE_ENUM,
        "type_name": ".linebot.safe_browsing.ThreatType",
    },
])
_schema.message_type.add(name="SearchUrlsResponse", field=[
    {
        "name": "threats", "number": 1,
        "label": FieldDescriptorProto.LABEL_REPEATED,
        "type": FieldDescriptorProto.TYPE_MESSAGE,
        "type_name": ".linebot.safe_browsing.ThreatUrl",
    },
    {
        "name": "cache_duration", "number": 2,
        "label": FieldDescriptorProto.LABEL_OPTIONAL,
        "type": FieldDescriptorProto.TYPE_MESSAGE,
        "type_name": ".google.protobuf.Duration",
    },
])
_pool = descriptor_pool.DescriptorPool()
_pool.AddSerializedFile(duration_pb2.DESCRIPTOR.serialized_pb)
_pool.Add(_schema)
SearchUrlsResponse = message_factory.GetMessageClass(
    _pool.FindMessageTypeByName("linebot.safe_browsing.SearchUrlsResponse"),
)
_KNOWN_THREAT_TYPES = frozenset(
    value.number for value in _threat_type.value if value.number != 0
)


def decode_safe_browsing_response(data: bytes) -> dict:
    """รับ bytes จาก Google; คืน dict หรือยก ValueError เมื่ออ่านผลไม่ได้."""
    if not isinstance(data, bytes):
        raise ValueError("Safe Browsing response must be bytes")

    response = SearchUrlsResponse()
    try:
        response.ParseFromString(data)
        result = MessageToDict(response)
    except (DecodeError, SerializeToJsonError):
        raise ValueError("Invalid Safe Browsing Protobuf response") from None

    # shortcut: enum ตาม public V5 ปัจจุบัน, เพิ่ม schema เมื่อ Google ส่งชนิดใหม่
    for threat in response.threats:
        for threat_type in threat.threat_types:
            if threat_type not in _KNOWN_THREAT_TYPES:
                raise ValueError("Unsupported Safe Browsing threat type")

    return result
