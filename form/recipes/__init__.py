from .base import Feature, Param, Recipe, RecipeError, Stage  # noqa: F401


def registry() -> dict:
    from .coupon import Coupon
    from .dock import Dock
    from .gridfinity import GridfinityBin
    from .hook import WallHook
    from .planter import TwistPlanter
    return {r.id: r for r in (Dock(), GridfinityBin(), WallHook(), TwistPlanter(), Coupon())}
