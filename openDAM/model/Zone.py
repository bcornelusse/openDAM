
class Zone:
    """
    Geographical zone where bids can be placed.

    :param id: identifier of the zone
    :param name: string name of the zone
    :param minimum_price: minimum price, can be negative
    :param maximum_price: maximum price.
    """

    def __init__(self, id, name, minimum_price, maximum_price):
        self.id = id
        self.name = name
        self.minimum_price = minimum_price
        self.maximum_price = maximum_price

