"""Opt-in cloud sync (feature 06, ADR-0004): push the library to rclone remotes.

Strictly local-first: nothing here runs unless ``[cloud].enabled = true``, and
the direction is push-only — sync never deletes local data (FR-8.4).
"""
