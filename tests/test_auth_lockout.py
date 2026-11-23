"""Pruebas de la política compartida, sin base real ni secretos.
Ejecutar: python -m unittest discover -s tests -v
"""
import sys
import types
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Este módulo puede probarse sin instalar Werkzeug en el equipo revisor.
# Sustituye solo la verificación de hash; la aplicación real usa Werkzeug.
try:
    from werkzeug import security as actual_security
except ImportError:
    pkg = types.ModuleType('werkzeug')
    security = types.ModuleType('werkzeug.security')
    security.check_password_hash = lambda stored, supplied: stored == f"hash:{supplied}"
    pkg.security = security
    sys.modules['werkzeug'] = pkg
    sys.modules['werkzeug.security'] = security

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shared_auth.security as auth
# Stubeamos solo para que los datos de ejemplo tengan un hash simple.
auth.check_password_hash = lambda stored, supplied: stored == f'hash:{supplied}'


class MemoryDB:
    def __init__(self):
        self.user = {'id': 2, 'nombre': 'Prueba', 'email': 'operador@example.test',
                     'rol': 'Operador', 'contrasena_hash': 'hash:clave-correcta',
                     'intentos_fallidos': 0, 'bloqueado_hasta': None,
                     'ultimo_intento_fallido': None, 'estado': 'Activo'}
        self.audit = []
        self.queries = []
        self.actor = 9
    def cursor(self):
        return MemoryCursor(self)
    def commit(self):
        pass
    def rollback(self):
        pass


class MemoryCursor:
    def __init__(self, db):
        self.db = db
        self.result = None
    def execute(self, sql, values=None):
        self.db.queries.append(sql)
        clean = ' '.join(sql.upper().split())
        u = self.db.user
        if clean.startswith('SELECT F.ID') and 'WHERE LOWER' in clean:
            if values[0].casefold() == u['email'].casefold() and u['estado'] == 'Activo':
                self.result = dict(u)
            else:
                self.result = None
        elif clean.startswith('SELECT F.ID') and 'WHERE F.ID' in clean:
            self.result = dict(u) if values[0] == u['id'] and u['estado'] == 'Activo' else None
        elif clean.startswith('UPDATE FICHA_PERSONAL'):
            if 'SET INTENTOS_FALLIDOS = 0' in clean:
                u.update({'intentos_fallidos': 0, 'bloqueado_hasta': None, 'ultimo_intento_fallido': None})
            elif len(values) == 4:
                failures, now, blocked_until, _ = values
                u.update({'intentos_fallidos': failures, 'ultimo_intento_fallido': now, 'bloqueado_hasta': blocked_until})
            else:
                failures, now, _ = values
                u.update({'intentos_fallidos': failures, 'ultimo_intento_fallido': now, 'bloqueado_hasta': None})
        elif clean.startswith('INSERT INTO AUDITORIA_DESBLOQUEOS'):
            self.db.audit.append(tuple(values))
        else:
            raise AssertionError(f'Consulta no simulada: {clean[:100]}')
    def fetchone(self):
        return self.result
    def close(self):
        pass


class LoginLockoutTests(unittest.TestCase):
    def setUp(self):
        self.db = MemoryDB()
    def login(self, password):
        return auth.authenticate(self.db, 'operador@example.test', password)[0]
    def test_three_failed_attempts_trigger_15_minutes(self):
        self.assertEqual(self.login('error'), 'invalid')
        self.assertEqual(self.db.user['intentos_fallidos'], 1)
        self.assertEqual(self.login('error'), 'invalid')
        self.assertEqual(self.db.user['intentos_fallidos'], 2)
        self.assertEqual(self.login('error'), 'locked')
        self.assertEqual(self.db.user['intentos_fallidos'], 3)
        remaining = self.db.user['bloqueado_hasta'] - datetime.now(timezone.utc)
        self.assertTrue(timedelta(minutes=14, seconds=50) < remaining <= timedelta(minutes=15))
        self.assertTrue(any('FOR UPDATE OF F' in q.upper() for q in self.db.queries))
    def test_correct_password_cannot_bypass_active_lock(self):
        for _ in range(3): self.login('error')
        self.assertEqual(self.login('clave-correcta'), 'locked')
        self.assertEqual(self.db.user['intentos_fallidos'], 3)
    def test_lock_expires_and_success_resets_counter(self):
        for _ in range(3): self.login('error')
        self.db.user['bloqueado_hasta'] = datetime.now(timezone.utc) - timedelta(seconds=2)
        self.assertEqual(self.login('clave-correcta'), 'ok')
        self.assertEqual(self.db.user['intentos_fallidos'], 0)
        self.assertIsNone(self.db.user['bloqueado_hasta'])
    def test_expired_lock_and_bad_password_starts_at_one(self):
        for _ in range(3): self.login('error')
        self.db.user['bloqueado_hasta'] = datetime.now(timezone.utc) - timedelta(seconds=2)
        self.assertEqual(self.login('error'), 'invalid')
        self.assertEqual(self.db.user['intentos_fallidos'], 1)
    def test_success_after_two_errors_resets_counter(self):
        self.login('error'); self.login('error')
        self.assertEqual(self.login('clave-correcta'), 'ok')
        self.assertEqual(self.db.user['intentos_fallidos'], 0)
    def test_unknown_email_returns_invalid_without_modifying_account(self):
        self.assertEqual(auth.authenticate(self.db, 'no-existe@example.test', 'x')[0], 'invalid')
        self.assertEqual(self.db.user['intentos_fallidos'], 0)
    def test_admin_unlock_is_audited(self):
        for _ in range(3): self.login('error')
        self.assertEqual(auth.unlock_account(self.db, 9, 'Administrador', 2), 'ok')
        self.assertEqual(self.db.audit, [(9, 2, 'Administrador')])
        self.assertEqual(self.login('clave-correcta'), 'ok')
    def test_supervisor_can_unlock_operator(self):
        for _ in range(3): self.login('error')
        self.assertEqual(auth.unlock_account(self.db, 11, 'Supervisor', 2), 'ok')
    def test_supervisor_cannot_unlock_admin(self):
        self.db.user['rol'] = 'Administrador'
        self.db.user['bloqueado_hasta'] = datetime.now(timezone.utc) + timedelta(minutes=14)
        self.assertEqual(auth.unlock_account(self.db, 11, 'Supervisor', 2), 'forbidden')
        self.assertTrue(self.db.user['bloqueado_hasta'] > datetime.now(timezone.utc))
        self.assertEqual(self.db.audit, [])
    def test_operator_cannot_unlock(self):
        self.db.user['bloqueado_hasta'] = datetime.now(timezone.utc) + timedelta(minutes=14)
        self.assertEqual(auth.unlock_account(self.db, 8, 'Operador', 2), 'forbidden')
        self.assertEqual(self.db.audit, [])
    def test_cannot_unlock_when_not_locked(self):
        self.assertEqual(auth.unlock_account(self.db, 9, 'Administrador', 2), 'not_locked')
        self.assertEqual(self.db.audit, [])


if __name__ == '__main__':
    unittest.main()
