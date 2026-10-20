"""Read the dedicated bot credential from an explicit macOS Keychain reference.

No plaintext credential files, command-line arguments, or diagnostic values.
The caller owns the operator-approved bot binding and service configuration.
"""
import ctypes
import re
import sys


class CredentialUnavailable(RuntimeError):
    pass


def bot_token(config, bot_id):
    if 'bot_token' in config:
        raise CredentialUnavailable('plaintext_bot_credential_not_allowed')
    reference = config.get('bot_token_keychain')
    if (not isinstance(reference, dict) or set(reference) != {'service', 'account'}
            or reference['service'] != 'openclaw.kai.telegram'
            or reference['account'] != str(bot_id)):
        raise CredentialUnavailable('invalid_bot_credential_reference')
    if sys.platform != 'darwin':
        raise CredentialUnavailable('credential_store_unavailable')
    security = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
    security.SecKeychainFindGenericPassword.argtypes = [ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    service, account = reference['service'].encode(), reference['account'].encode()
    size, data = ctypes.c_uint32(), ctypes.c_void_p()
    status = security.SecKeychainFindGenericPassword(None, len(service), service,
        len(account), account, ctypes.byref(size), ctypes.byref(data), None)
    if status != 0:
        raise CredentialUnavailable('credential_store_unavailable')
    try:
        if not 25 <= size.value <= 128:
            raise CredentialUnavailable('invalid_bot_credential')
        value = ctypes.string_at(data, size.value).decode('ascii')
        if not re.fullmatch(str(bot_id) + r':[A-Za-z0-9_-]{20,100}', value):
            raise CredentialUnavailable('invalid_bot_credential')
        return value
    except (UnicodeError, ValueError):
        raise CredentialUnavailable('invalid_bot_credential') from None
    finally:
        security.SecKeychainItemFreeContent(None, data)
