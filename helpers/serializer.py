import hashlib
import re

def zigzag(i):
    return (i >> 63) ^ (i << 1)


def vlq(i):
    ret = []
    while i != 0:
        b = i & 0x7F
        i >>= 7
        if i > 0:
            b |= 0x80
        ret.append(b)
    return ret


def encode_long(n):
    if n == 0:
        return "0500"
    z = zigzag(n)
    v = vlq(z)
    r = '05' + ''.join(['{0:02x}'.format(i) for i in v])
    return r


def encode_int(n: int):
    if n == 0:
        return "0400"
    z = zigzag(n)
    v = vlq(z)
    r = '04' + ''.join(['{0:02x}'.format(i) for i in v])
    return r


def bad_encode_long(n: int):
    if n == 0:
        return "00"
    z = zigzag(n)
    v = vlq(z)
    r = ''.join(['{0:02x}'.format(i) for i in v])
    return r


def encode_long_tuple(arr):
    res = "11"
    length_vlq = vlq(len(arr))
    res += ''.join(['{0:02x}'.format(i) for i in length_vlq])
    for long in arr:
        res += bad_encode_long(long)
    return res


def encode_long_pair(entry1, entry2):
    return '59' + encode_long(entry1)[2:] + encode_long(entry2)[2:]


def encode_coll_int(arr):
    res = "10" + '{0:02x}'.format(len(arr))
    for long in arr:
        res += bad_encode_long(long)
    return res


def encode_int_tuple(arr):
    res = "4004"
    for long in arr:
        res += bad_encode_long(long)
    return res


def hex_to_base58(hex_string):
    base58_alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

    # Convert hex string to an integer
    num = int(hex_string, 16)

    # Encode the integer to Base58
    base58_string = ""
    while num > 0:
        num, remainder = divmod(num, 58)
        base58_string = base58_alphabet[remainder] + base58_string

    # Handle leading zeros
    num_leading_zeros = len(hex_string) - len(hex_string.lstrip('0'))
    num_leading_zeros //= 2  # Each pair of hex digits represents a byte

    return '1' * num_leading_zeros + base58_string

def bytesLike(hex_text):
    """
    This function Convert ergo tree addresses into bytes-like values.
    """
    return bytes.fromhex(hex_text)

def blake2b256(bytes_value):
    """
    This function compute blake2b256 hash
    """
    h = hashlib.blake2b(person = b'', digest_size=32)
    h.update(bytes_value)
    return h.hexdigest()

def encode_bigint(v):
    # Convert integer to a bytearray in big-endian byte order and strip any leading zeros
    bytes_array = v.to_bytes((v.bit_length() + 7) // 8, byteorder='big', signed=True) or b'\x00'

    # Encode the length of the bytearray using VLQ
    length_encoded = vlq(len(bytes_array))

    # Convert all parts to hexadecimal strings
    num_bytes_hex = ''.join(f'{byte:02x}' for byte in length_encoded)
    bytes_hex = ''.join(f'{byte:02x}' for byte in bytes_array)

    # Combine parts into the final serialized format
    result = num_bytes_hex + bytes_hex
    return "06" + result


def extract_number(s):
    """
    Extracts the number from a string formatted as CBigInt(number).

    Parameters:
    s (str): The input string containing the number.

    Returns:
    str: The extracted number as a string, or None if no number is found.
    """
    match = re.search(r'CBigInt\((\d+)\)', s)
    if match:
        return int(match.group(1))
    else:
        return None