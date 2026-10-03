"""Shared periodic notification generation, independent of delivery."""
import asyncio

STATUS_INTERVAL_SECONDS = 15 * 60


async def periodic_status(state, engine):
    while True:
        await asyncio.sleep(STATUS_INTERVAL_SECONDS)
        state.event(engine.summary())
