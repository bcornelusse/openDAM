class Line:
    """
    :param from_id: id of origin bidding area (or location).
    :param to_id: id of origin bidding area (or location).
    :param capacity_up: dict with capacities per period in normal direction.
    :param capacity_down: dict with capacities per period in reverse direction.
    """

    def __init__(self, id, f, t, c_up, c_down):
        self.line_id = id
        self.from_id = f
        self.to_id = t
        self.capacity_up = c_up
        self.capacity_down = c_down
        self.flow_up = None
        self.flow_down = None
        #congestion_up = None
        #congestion_down = None