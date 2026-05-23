"""
Stub for blackboxprotobuf — the upstream goofish_utils imports this module
but never calls any of its functions. This stub avoids the protobuf==3.10.0
version conflict that the real blackboxprotobuf==1.0.1 forces.
"""
# No-op stub: expose common API surface so any future actual calls fail loudly
def decode_message(*args, **kwargs):
    raise NotImplementedError("blackboxprotobuf stub: decode_message not implemented")

def encode_message(*args, **kwargs):
    raise NotImplementedError("blackboxprotobuf stub: encode_message not implemented")
