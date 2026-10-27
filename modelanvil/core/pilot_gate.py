"""Commercial claims stay closed until a person records pilot evidence.

The automated activation baseline is a software fixture. It does not open
customer discovery or paid packaging.
"""

CUSTOMER_DISCOVERY = 'open'
PAID_PACKAGING = 'closed'
REASON = (
    'Paid packaging stays closed until observed human pilots complete a second improvement cycle. '
    'The automated activation script is not that evidence. Customer discovery remains the open gate in GitHub issue 16.'
)


def commercial_status():
    return {
        'customer_discovery': CUSTOMER_DISCOVERY,
        'paid_packaging': PAID_PACKAGING,
        'commercial_reason': REASON,
    }


def paid_packaging_allowed():
    return PAID_PACKAGING == 'open' and CUSTOMER_DISCOVERY == 'complete'
