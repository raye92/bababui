"""Native field definitions in header section 632 (CATalyst 22.1).

Controlled Fill In Field saves retain the stream reference and change this
table: u32 count, count 128-byte descriptors, then their length-delimited values.
The opaque descriptor bytes are retained; offsets 72 and 80 store value lengths.
"""
from dataclasses import dataclass
import struct
import zlib


def field_record(name):
    encoded = name.encode('cp1252')
    if not encoded or len(encoded) > 63 or any(value < 32 for value in encoded):
        raise ValueError('Field names must contain 1 to 63 Windows-1252 characters.')
    identifier = struct.pack('<I', ~zlib.crc32(encoded) & 0xffffffff)
    return b'\x15\x07' + struct.pack('<I', len(encoded) + 5) + identifier + encoded + b'\0'


@dataclass(frozen=True)
class FieldDefinition:
    name: str
    identifier: bytes
    descriptor: bytes
    value: bytes


def read_fields(native):
    offset, size = struct.unpack_from('<II', native, 632)
    if not offset and not size:
        return ()
    if size < 4 or offset < 1024 or offset + size > len(native):
        raise ValueError('Unsupported native field table.')
    data = native[offset:offset + size]
    count = struct.unpack_from('<I', data)[0]
    cursor = 4 + count * 128
    if cursor > len(data):
        raise ValueError('Unsupported native field descriptors.')
    result, names = [], set()
    for index in range(count):
        descriptor = data[4 + index * 128:4 + (index + 1) * 128]
        if b'\0' not in descriptor[:64]:
            raise ValueError('Invalid native field name.')
        name = descriptor[:64].split(b'\0', 1)[0].decode('cp1252')
        length = struct.unpack_from('<I', descriptor, 72)[0]
        if name in names or cursor + length > len(data):
            raise ValueError('Invalid native field value.')
        result.append(FieldDefinition(name, descriptor[64:68], descriptor, data[cursor:cursor+length]))
        names.add(name)
        cursor += length
    if cursor != len(data):
        raise ValueError('Unaccounted native field data.')
    return tuple(result)


def field_texts(native):
    # Field values may themselves contain native hard spaces. Other formatting
    # remains in the table and is rejected for editing until it is understood.
    return {field.name: field.value.replace(b'\x01', b' ').decode('cp1252') for field in read_fields(native)}


def rewrite_fields(native, values):
    if not values:
        return native
    fields = list(read_fields(native))
    for name in sorted(set(values) - {field.name for field in fields}):
        raw = field_record(name)
        descriptor = bytearray(128)
        descriptor[:len(raw[10:])] = raw[10:]
        descriptor[64:68] = raw[6:10]
        struct.pack_into('<I', descriptor, 84, 32)
        struct.pack_into('<I', descriptor, 92, 4)
        fields.append(FieldDefinition(name, raw[6:10], bytes(descriptor), b''))
    fields.sort(key=lambda field: int.from_bytes(field.identifier, 'little'))
    descriptors, payloads = [], []
    for field in fields:
        value = values[field.name].encode('cp1252') if field.name in values else field.value
        descriptor = bytearray(field.descriptor)
        struct.pack_into('<I', descriptor, 72, len(value))
        if field.name in values:
            struct.pack_into('<I', descriptor, 80, len(value))
        descriptors.append(descriptor)
        payloads.append(value)
    table = struct.pack('<I', len(fields)) + b''.join(descriptors) + b''.join(payloads)
    offset, size = struct.unpack_from('<II', native, 632)
    if not offset and not size:
        result = bytearray(native)
        struct.pack_into('<II', result, 632, len(result), len(table))
        result += table
        read_fields(result)
        return bytes(result)
    end, delta = offset + size, len(table) - size
    result = bytearray(native)
    # Stream positions are unchanged. Relocate container section addresses,
    # including extended streams, independently of their on-disk order.
    index, index_size = struct.unpack_from('<II', native, 588)
    directory = index + index_size
    if native[directory:directory+8] != b'2XSTRMZ\0':
        raise ValueError('Missing native extended-stream directory.')
    count = struct.unpack_from('<I', native, directory+8)[0]
    pointers = [540, 548, 556, 564, 572, 580, 588, 612, 644]
    pointers += list(range(directory+32, directory+32+count*8, 8))
    for position in pointers:
        address = struct.unpack_from('<I', native, position)[0]
        if address >= end:
            struct.pack_into('<I', result, position, address + delta)
    struct.pack_into('<I', result, 636, len(table))
    result[offset:end] = table
    read_fields(result)
    return bytes(result)
