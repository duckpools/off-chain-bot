"""
Debug configuration for tracking specific user addresses.
All activity for these addresses is logged to sync_services.log for profit debugging.
"""
from logger import set_logger

# Logger that writes to sync_services.log for debug tracing
debug_logger = set_logger('profit_debug', log_file='sync_services.log')

# Addresses to trace — all activity involving these addresses gets detailed logging
DEBUG_ADDRESSES = {
    "9gSsDJixycevrHL7xxD7dr9R9G3Mi4W7LVohvK1GAjycsJc7zSy",
    "9ffADd9WQ5cuxnmNu2ryarpSaQ7w1Xeka9gwvVNppArgFN7xjEN",
    "9hGxTdZKhZ12eZNzg7mCGRpuHTvxayNm7gxPz6rmbMtVpjdjYQh",
    "9fgkQ85sd5BZRewkicHwsPvUcTerKjKXesuaxfNjoFoVU9Xe3aQ",
    "9fuot9tX8TgRc7onngrwSC8vR1Jb8mCE4uhAaZ9qUtZCjinMPuw",
    "9i4ZQu3S6Wv5uBrAVRBksmTdAkrs5G1dPT7An4u4Uo8XCbA5A9R",
    "9h8P9p9M6PuMnGV8tywSsurK9DLBhpQ2Pjp3Wfha1QjAqJvK6S2",
    "9i3frAZfzm3qfiS1Eks21BA7JJkkXEMhdGuycEeDhT3D3VzBmLW",
    "9gjBFycwWRHSJdoFsm2dEBukF73Tz2JPxK2FEQW2MeXiS5cmQ7V",
    "9gFsyHpSspiAj7dda7ioY7fUuvbAnKZNs3chfMeRmBR524YVVyp",
    "9fb6r2oyKmNCjpa4so2c1A9wnuyBzFVJngQExyGWirhZw65TGbN",
    "9gYtJiqF7YbuV2n745PseWWQKVZbSw3YUc8adWCompAQyn51Pbn",
    "9gekpTJfDM4uuWt2CGBMHonG3DbFqmx7LN4EHzmA6rvCbaCWgds",
    "9hMDYmHwkd5ADZsa5UdskghiaTj69fhStpXcJLQgxyENNENrMaQ",
    "9ezmUenPY3KEms7KLJ7NPG9NNCk894ysmK9rQuHF1ytKcNNE1E5",
    "9hGySniqiyYci5xHxZE9RNt1MHYmXbgtgQFyFaGj8oHFvp17NVn",
}


def is_debug_address(address: str) -> bool:
    """Check if an address is in the debug set."""
    return address in DEBUG_ADDRESSES
