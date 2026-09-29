// =============================================================================
// EvalCaseDialog — agregar un caso de prueba sin tocar JSON.
// =============================================================================
// Un caso = pregunta + (opcional) respuesta esperada + comportamiento esperado
// + fuentes esperadas. También acepta un CSV para cargar varios de una vez.
// =============================================================================
import { FloppyDisk, UploadSimple } from "@phosphor-icons/react";
import { useEffect, useState, type FormEvent } from "react";
import { api, type Session } from "../../api";
import {
  Button,
  ErrorInline,
  Field,
  Input,
  Modal,
  Select,
  SuccessInline,
  Textarea,
} from "../ui";

type DatasetOption = { id: string; name: string; case_count?: number };

const BEHAVIORS = [
  { value: "answer", label: "Debe responder" },
  { value: "abstain", label: "Debe abstenerse (falta evidencia o contexto)" },
] as const;

export function EvalCaseDialog({
  open,
  onOpenChange,
  session,
  dataset,
  presetQuestion = "",
  presetAnswer = "",
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session?: Session | null;
  /** Dataset fijo para el que se agrega el caso (si se conoce). */
  dataset?: DatasetOption | null;
  presetQuestion?: string;
  presetAnswer?: string;
  onSaved?: (dataset: DatasetOption) => void;
}) {
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [datasetId, setDatasetId] = useState(dataset?.id || "");
  const [question, setQuestion] = useState(presetQuestion);
  const [expectedAnswer, setExpectedAnswer] = useState(presetAnswer);
  const [behavior, setBehavior] = useState<string>("answer");
  const [sources, setSources] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!open) return;
    setQuestion(presetQuestion);
    setExpectedAnswer(presetAnswer);
    setBehavior("answer");
    setSources("");
    setDatasetId(dataset?.id || "");
    setError("");
    setMsg("");
    if (!session) return;
    api<{ datasets: DatasetOption[] }>("/api/v1/eval/datasets", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => setDatasets(out.datasets || []))
      .catch(() => setDatasets([]));
  }, [open, dataset?.id, presetQuestion, presetAnswer, session]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!session || !datasetId || !question.trim()) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const expectedSources = sources
        .split(/[;|]/)
        .map((value) => value.trim())
        .filter(Boolean);
      await api(`/api/v1/eval/datasets/${datasetId}/examples`, {
        method: "POST",
        token: session.token,
        organizationId: session.organizationId,
        body: JSON.stringify({
          examples: [
            {
              question: question.trim(),
              expected_answer: expectedAnswer.trim() || null,
              expected_behavior: behavior,
              expected_sources: expectedSources,
            },
          ],
        }),
      });
      const target = datasets.find((ds) => ds.id === datasetId) || dataset;
      setMsg("Caso agregado. Ya cuenta para el próximo run.");
      onSaved?.(target ?? { id: datasetId, name: "" });
      if (!onSaved) onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo agregar el caso");
    } finally {
      setBusy(false);
    }
  }

  async function onCsv(file: File) {
    if (!session || !datasetId) return;
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const csv = await file.text();
      const out = await api<{ count: number }>(
        `/api/v1/eval/datasets/${datasetId}/import-csv`,
        {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ csv }),
        },
      );
      setMsg(`${out.count} casos cargados desde el CSV.`);
      const target = datasets.find((ds) => ds.id === datasetId) || dataset;
      onSaved?.(target ?? { id: datasetId, name: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo importar el CSV");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next && busy) return;
        if (!next) onOpenChange(false);
      }}
      title="Agregar caso de prueba"
      description="Describe una pregunta real y qué esperas que haga el agente. Nada de JSON."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Cerrar
          </Button>
          <Button
            type="submit"
            form="eval-case-form"
            variant="primary"
            loading={busy}
            leadingIcon={FloppyDisk}
            disabled={!datasetId || !question.trim()}
          >
            Agregar caso
          </Button>
        </>
      }
    >
      <form id="eval-case-form" className="flex flex-col gap-4" onSubmit={onSubmit}>
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />

        {!dataset && (
          <Field label="Dataset" required>
            <Select
              id="eval-case-dataset"
              value={datasetId}
              onChange={(ev) => setDatasetId(ev.target.value)}
              placeholder="Selecciona un dataset…"
              required
            >
              {datasets.map((ds) => (
                <option key={ds.id} value={ds.id}>
                  {ds.name}
                </option>
              ))}
            </Select>
          </Field>
        )}

        <Field
          label="Pregunta"
          required
          hint="Escribe la pregunta tal como la haría una persona del equipo."
        >
          <Textarea
            className="min-h-16"
            value={question}
            onChange={(ev) => setQuestion(ev.target.value)}
            placeholder="¿Qué cubre la categoría 31?"
            required
          />
        </Field>

        <Field
          label="Respuesta esperada (opcional)"
          hint="Si la dejas vacía, el juez solo mide relevancia y fidelidad."
        >
          <Textarea
            className="min-h-16"
            value={expectedAnswer}
            onChange={(ev) => setExpectedAnswer(ev.target.value)}
          />
        </Field>

        <Field
          label="Comportamiento esperado"
          hint="'Debe abstenerse' mide answerability: no castiga que diga que no sabe."
        >
          <Select
            id="eval-case-behavior"
            value={behavior}
            onChange={(ev) => setBehavior(ev.target.value)}
          >
            {BEHAVIORS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </Field>

        <Field
          label="Fuentes esperadas (opcional)"
          hint="Nombres separados por ; o |. Se usan para medir retrieval."
        >
          <Input
            value={sources}
            onChange={(ev) => setSources(ev.target.value)}
            placeholder="Cat31_dapp_C.pdf; NDC Reference"
          />
        </Field>

        <div className="border-t border-border-soft pt-3">
          <label className="flex items-center gap-2 text-[12.5px] text-muted">
            <UploadSimple size={15} aria-hidden />
            <span>O carga varios desde un CSV</span>
            <input
              type="file"
              accept=".csv,text/csv"
              className="block w-full cursor-pointer text-[12.5px] text-muted file:mr-3 file:cursor-pointer file:rounded-sm file:border file:border-border file:bg-raised file:px-3 file:py-1.5 file:text-[12.5px] file:font-medium file:text-text"
              disabled={busy || !datasetId}
              onChange={(ev) => {
                const file = ev.target.files?.[0];
                if (file) void onCsv(file);
              }}
            />
          </label>
          <p className="mt-1.5 text-[11px] text-faint">
            Cabecera: question,expected_answer,expected_behavior,expected_sources,must_cite
          </p>
        </div>
      </form>
    </Modal>
  );
}
