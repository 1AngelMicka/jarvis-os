"""Suspendre et reprendre un processus (pause réelle d'un atelier Claude Code).

Windows : `NtSuspendProcess` / `NtResumeProcess` sur le processus de Claude Code. POSIX : `SIGSTOP` / `SIGCONT` à
tout son groupe (Claude Code y est lancé dans sa propre session). Une commande déjà lancée par Claude Code sous
Windows peut finir son travail ; aucune nouvelle ne part, puisque ses autorisations sont retenues pendant la pause.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import sys

journal = logging.getLogger("jarvis2.ateliers")

PROCESS_SUSPEND_RESUME = 0x0800


def suspendre(pid: int, oui: bool) -> bool:
    """Suspend (`oui`) ou reprend le processus ; False si le système l'a refusé (la pause reste celle des
    autorisations)."""
    try:
        if sys.platform == "win32":
            import ctypes

            noyau, ntdll = ctypes.windll.kernel32, ctypes.windll.ntdll
            poignee = noyau.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
            if not poignee:
                return False
            try:
                appel = ntdll.NtSuspendProcess if oui else ntdll.NtResumeProcess
                return int(appel(poignee)) == 0
            finally:
                noyau.CloseHandle(poignee)
        signal_ = signal.SIGSTOP if oui else signal.SIGCONT
        groupe = os.getpgid(pid)
        if groupe == os.getpgid(0):  # jamais le groupe du Core lui-même
            os.kill(pid, signal_)
        else:
            os.killpg(groupe, signal_)
        return True
    except (OSError, AttributeError) as exc:
        with contextlib.suppress(Exception):
            journal.warning("Suspension du processus %s impossible : %s", pid, exc)
        return False
