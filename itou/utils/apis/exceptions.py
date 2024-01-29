class GeocodingDataError(Exception):
    "Generic exception for geolocation API. May be subclassed for more fine grained issues."


class AddressLookupError(GeocodingDataError): ...
