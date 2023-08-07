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
