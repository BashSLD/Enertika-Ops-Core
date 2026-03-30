---
name: asyncpg - conexión única no es concurrente
description: Una sola conexión asyncpg no puede ejecutar queries en paralelo — asyncio.gather con el mismo conn falla
type: feedback
---

No usar `asyncio.gather()` con el mismo objeto `conn` para paralelizar queries en asyncpg.

**Why:** Una conexión asyncpg solo puede ejecutar un query a la vez. Dos coroutines sobre el mismo `conn` se serializan o generan error. La propuesta de gather es un false positive recurrente en code review.

**How to apply:** Si se necesita paralelismo real, adquirir conexiones separadas del pool. En endpoints FastAPI normales con `Depends(get_db_connection)`, cada request tiene una sola conexión — los queries van siempre en secuencia.
