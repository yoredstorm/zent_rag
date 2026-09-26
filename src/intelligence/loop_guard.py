# =============================================================================
# Loop Prevention — fingerprints deterministas y retry con nueva información
# =============================================================================
# Una operación idéntica no puede ejecutarse reiteradamente sin que exista
# nueva información que justifique el retry. Se registra:
#   retry_reason / previous_attempt / new_information / modified_plan
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from src.core.domain.intelligence import ToolFingerprint


@dataclass
class RetryRecord:
    """Registro de un retry permitido (trazabilidad de loop prevention)."""

    fingerprint_digest: str
    retry_reason: str
    previous_attempt: int
    new_information: str
    modified_plan: bool = False


class LoopGuard:
    """Guarda de loops: bloquea operaciones idénticas sin nueva información."""

    #: Cuántas veces se puede liberar un fingerprint ya registrado. Un intento
    #: que falló por el proveedor (429/5xx/timeout) no produjo información, así
    #: que su reintento no es un duplicado; pero el perdón está acotado para que
    #: un fallo permanente no se vuelva un reintento infinito.
    MAX_RELEASES = 1

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self._observations: dict[str, str] = {}
        self._released: dict[str, int] = {}
        self.retry_records: list[RetryRecord] = []
        self.prevented: int = 0

    def check(
        self,
        fingerprint: ToolFingerprint,
        *,
        observation_context: str = "",
        new_information: str | None = None,
        retry_reason: str = "new_information",
        modified_plan: bool = False,
    ) -> bool:
        """True = la operación puede ejecutarse; False = loop detectado.

        Un retry solo se permite si:
          - es la primera vez (siempre permitida), o
          - el contexto de observación cambió (la última observación difiere), o
          - se declara explícitamente nueva información (new_information).
        """
        digest = fingerprint.digest
        previous = self._seen.get(digest, 0)
        if previous == 0:
            self._seen[digest] = 1
            self._observations[digest] = observation_context
            return True

        last_observation = self._observations.get(digest, "")
        changed = last_observation != observation_context
        if changed:
            self.retry_records.append(
                RetryRecord(
                    fingerprint_digest=digest,
                    retry_reason="observation_changed",
                    previous_attempt=previous,
                    new_information="El contexto de observación cambió",
                )
            )
            self._seen[digest] = previous + 1
            self._observations[digest] = observation_context
            return True

        if new_information:
            self.retry_records.append(
                RetryRecord(
                    fingerprint_digest=digest,
                    retry_reason=retry_reason,
                    previous_attempt=previous,
                    new_information=new_information,
                    modified_plan=modified_plan,
                )
            )
            self._seen[digest] = previous + 1
            return True

        self.prevented += 1
        return False

    def release(
        self, fingerprint: ToolFingerprint, *, reason: str = "failed_attempt"
    ) -> bool:
        """Deshace el registro de un intento que no llegó a ejecutarse.

        Se llama cuando la ejecución terminó en un fallo TRANSITORIO del
        proveedor: no hubo observación, así que el fingerprint no debería contar
        como "ya visto" y el reintento tiene que poder pasar. Devuelve True si
        quedó libre.
        """
        digest = fingerprint.digest
        previous = self._seen.get(digest, 0)
        if previous <= 0:
            return False
        released = self._released.get(digest, 0)
        if released >= self.MAX_RELEASES:
            return False
        self._released[digest] = released + 1
        remaining = previous - 1
        if remaining > 0:
            self._seen[digest] = remaining
        else:
            self._seen.pop(digest, None)
            self._observations.pop(digest, None)
        self.retry_records.append(
            RetryRecord(
                fingerprint_digest=digest,
                retry_reason=reason,
                previous_attempt=previous,
                new_information="El intento anterior falló sin ejecutarse",
            )
        )
        return True

    @property
    def prevented_count(self) -> int:
        return self.prevented


class SQLRepairGuard:
    """Corta el loop de reparación SQL: (sql, error) idéntico repetido se detiene."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}
        self.prevented: int = 0

    @staticmethod
    def _key(sql: str, error: str) -> str:
        return f"{sql.strip().lower()}|{error.strip().lower()}"

    def allow(self, sql: str, error: str) -> bool:
        """True si el repair puede intentarse; False si (sql, error) ya se repitió."""
        key = self._key(sql, error)
        count = self._seen.get(key, 0)
        if count >= 1:
            self.prevented += 1
            return False
        self._seen[key] = count + 1
        return True
