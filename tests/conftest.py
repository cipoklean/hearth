import os

import pytest
import pytest_asyncio

os.environ["HEARTH_MOCK"] = "1"

from hearth.models import Need, Profile  # noqa: E402
from hearth.qloo import QlooClient  # noqa: E402


@pytest_asyncio.fixture
async def client():
    c = QlooClient(mock=True)
    yield c
    await c.aclose()


async def _ent(client, name, domain):
    res = await client.search(name, types=[domain], take=1)
    assert res, name
    return res[0]


@pytest_asyncio.fixture
async def ada(client):
    """Likes 1940s big band; needs soft food, mild films, step-free access."""
    marlow = await _ent(client, "The Marlow Sisters", "artist")
    return Profile(resident_id="ada", name="Ada", entities=[marlow],
                   needs=[Need.soft_food, Need.mild_content, Need.wheelchair_access])


@pytest_asyncio.fixture
async def bayo(client):
    teddy = await _ent(client, "Teddy Okafor & His Highlife Band", "artist")
    return Profile(resident_id="bayo", name="Bayo", entities=[teddy])


@pytest_asyncio.fixture
async def cy(client):
    metal = await _ent(client, "Grindcore Unit", "artist")
    return Profile(resident_id="cy", name="Cy", entities=[metal])
