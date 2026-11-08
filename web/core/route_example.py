"""Run a fixed read-only route rotation example in a browser or Python."""

import json

from open_items_routes import OpenItemsRouter


def run_example():
    items = [
        {"id": 9, "state": "open"},
        {"id": 4, "state": "closed"},
        {"id": 2, "state": "open"},
    ]
    router = OpenItemsRouter()
    runs = [router.run(items) for _ in range(4)]
    return {"items": items, "runs": runs}


if __name__ == "__main__":
    print(json.dumps(run_example(), indent=2))
