import pyotp


def generate_otp_secret():
    return pyotp.random_base32()


def verify_otp(otp_secret, otp):
    totp = pyotp.TOTP(otp_secret)
    return totp.verify(otp)
