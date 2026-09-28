"""Current-user secret storage: Windows DPAPI or Linux Secret Service."""

import base64
import ctypes
import sys
import uuid
from ctypes import wintypes


_PREFIX = "dpapi:"
_KEYRING_PREFIX = "keyring:secret-service:"
_KEYRING_SERVICE = "iface/ai-credentials"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _require_windows():
    if sys.platform != "win32":
        raise OSError("This credential is encrypted for a Windows user. Save the key again on this computer.")


def _linux_keyring():
    """Select the native encrypted service explicitly, never a plaintext fallback."""
    if not sys.platform.startswith("linux"):
        raise OSError("Native secret storage is supported on Windows and Linux.")
    try:
        from keyring.backends.SecretService import Keyring

        backend = Keyring()
        if backend.priority <= 0:
            raise RuntimeError("Secret Service is unavailable")
        return backend
    except Exception as exc:
        raise OSError("Secure key storage needs an unlocked Linux Secret Service keyring "
                      "(such as GNOME Keyring or compatible KWallet) in your desktop session.") from exc


def _keyring_id(value):
    reference = value[len(_KEYRING_PREFIX):]
    try:
        if uuid.UUID(reference).hex != reference:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError("The saved keyring reference is invalid.") from exc
    return reference


def protect_secret(secret):
    """Keep a secret in current-user protected storage; return a nonsecret reference."""
    value = str(secret or "")
    if not value:
        return ""
    if sys.platform == "win32":
        return _protect_windows_secret(value)
    backend = _linux_keyring()
    reference = uuid.uuid4().hex
    try:
        backend.set_password(_KEYRING_SERVICE, reference, value)
    except Exception as exc:
        raise OSError("The Linux keyring could not save the API key. Unlock your keyring and try again.") from exc
    return _KEYRING_PREFIX + reference


def unprotect_secret(protected_secret):
    """Read a secret using the same OS user account that originally saved it."""
    value = str(protected_secret or "")
    if not value:
        return ""
    if value.startswith(_PREFIX):
        return _unprotect_windows_secret(value)
    if not value.startswith(_KEYRING_PREFIX):
        raise ValueError("The saved API key format is invalid.")
    reference = _keyring_id(value)
    backend = _linux_keyring()
    try:
        secret = backend.get_password(_KEYRING_SERVICE, reference)
    except Exception as exc:
        raise OSError("The Linux keyring could not read the API key. Unlock your keyring and try again.") from exc
    if secret is None:
        raise OSError("The saved API key is missing from this user's keyring. Save it again.")
    return secret


def remove_secret(protected_secret):
    """Remove an external keyring entry; embedded DPAPI values need no cleanup."""
    value = str(protected_secret or "")
    if not value or value.startswith(_PREFIX):
        return
    if not value.startswith(_KEYRING_PREFIX):
        raise ValueError("The saved API key format is invalid.")
    reference = _keyring_id(value)
    backend = _linux_keyring()
    try:
        if backend.get_password(_KEYRING_SERVICE, reference) is not None:
            backend.delete_password(_KEYRING_SERVICE, reference)
    except Exception as exc:
        raise OSError("The Linux keyring could not remove the API key. Unlock your keyring and try again.") from exc


def _input_blob(payload):
    buffer = ctypes.create_string_buffer(payload)
    blob = _DataBlob(
        len(payload),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def _protect_windows_secret(secret):
    """Encrypt a string so only the current Windows user can decrypt it."""
    _require_windows()
    payload = str(secret or "").encode("utf-8")
    if not payload:
        return ""

    source, source_buffer = _input_blob(payload)
    protected = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    # Keep source_buffer alive until CryptProtectData has returned.
    _ = source_buffer
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "iface 2.0 AI API key",
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(protected),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        encrypted = ctypes.string_at(protected.pbData, protected.cbData)
    finally:
        kernel32.LocalFree(protected.pbData)
    return _PREFIX + base64.b64encode(encrypted).decode("ascii")


def _unprotect_windows_secret(protected_secret):
    """Decrypt a value created by :func:`protect_secret`."""
    _require_windows()
    value = str(protected_secret or "")
    if not value:
        return ""
    if not value.startswith(_PREFIX):
        raise ValueError("The saved API key format is invalid.")
    try:
        encrypted = base64.b64decode(value[len(_PREFIX) :], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("The saved API key data is damaged.") from exc

    source, source_buffer = _input_blob(encrypted)
    decrypted = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    _ = source_buffer
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(decrypted),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        plaintext = ctypes.string_at(decrypted.pbData, decrypted.cbData)
    finally:
        kernel32.LocalFree(decrypted.pbData)
    return plaintext.decode("utf-8")
