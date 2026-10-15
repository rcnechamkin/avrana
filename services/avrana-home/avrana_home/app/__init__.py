"""Avrana home web application (proposed, NOT deployed; synthetic data only).

The modules that need no framework (`settings`, `catalogue`, `routing`, `viewmodel`, `logsafe`)
import with the standard library alone, so they are tested everywhere. Only `main` (the FastAPI
app factory), `identity` and `middleware` need FastAPI/Starlette. Importing this package starts
nothing and reads no environment.
"""
