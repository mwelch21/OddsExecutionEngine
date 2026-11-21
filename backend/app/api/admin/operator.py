def require_operator() -> None:
    """The one gate on every Admin view route (ADR-018).

    A no-op today: there is no auth yet. Auth (#14) fills this in, and every route
    on the admin router is gated at once.
    """
