// =============================================================================
// EvalCaseDialog — agregar o editar un caso de prueba sin tocar JSON.
// =============================================================================
// Un caso = pregunta + (opcional) respuesta esperada + comportamiento esperado
// + fuentes esperadas. Sin dataset fijo permite crear uno en el momento.
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

/** Valor centinela del selector para crear un dataset en el momento. */
const NEW_DATASET = "__nuevo__";

const BEHAVIORS = [
  { value: "answer", label: "Debe responder" },
  { value: "abstain", label: "Debe abstenerse (falta evidencia o contexto)" },
] as const;

export type EvalCaseInitial = {
  question?: string;
  expected_answer?: string | null;
  expected_behavior?: string | null;
  expected_sources?: string[];
};

export function EvalCaseDialog({
  open,
  onOpenChange,
  session,
  dataset,
  caseId,
  initial,
  presetQuestion = "",
  presetAnswer = "",
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session?: Session | null;
  /** Dataset fijo (si se conoce). Sin él se elige o se crea uno. */
  dataset?: DatasetOption | null;
  /** Id del ejemplo cuando se edita un caso existente. */
  caseId?: string;
  initial?: EvalCaseInitial;
  presetQuestion?: string;
  presetAnswer?: string;
  onSaved?: (dataset: DatasetOption) => void;
}) {
  const isEdit = Boolean(caseId);
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [datasetId, setDatasetId] = useState(dataset?.id || "");
  const [newDatasetName, setNewDatasetName] = useState("");
  const [question, setQuestion] = useState(presetQuestion);
  const [expectedAnswer, setExpectedAnswer] = useState(presetAnswer);
  const [behavior, setBehavior] = useState<string>("answer");
  const [sources, setSources] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!open) return;
    setQuestion(initial?.question ?? presetQuestion);
    setExpectedAnswer(initial?.expected_answer ?? presetAnswer);
    const initialBehavior = (initial?.expected_behavior || "").toLowerCase();
    setBehavior(
      initialBehavior.includes("abst") || initialBehavior.includes("human")
        ? "abstain"
        : "answer",
    );
    setSources((initial?.expected_sources || []).join("; "));
    setDatasetId(dataset?.id || "");
    setNewDatasetName("");
    setError("");
    setMsg("");
    if (!session || dataset) return;
    api<{ datasets: DatasetOption[] }>("/api/v1/eval/datasets", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((out) => {
        const list = out.datasets || [];
        setDatasets(list);
        setDatasetId((current) => current || list[0]?.id || NEW_DATASET);
      })
      .catch(() => setDatasets([]));
  }, [
    open,
    dataset,
    caseId,
    presetQuestion,
    presetAnswer,
    initial?.question,
    initial?.expected_answer,
    initial?.expected_behavior,
    initial?.expected_sources,
    session,
  ]);

  const creatingDataset = !dataset && datasetId === NEW_DATASET;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!session || !question.trim()) return;
    if (creatingDataset && !newDatasetName.trim()) {
      setError("Ponle un nombre al nuevo dataset.");
      return;
    }
    setBusy(true);
    setError("");
    setMsg("");
    try {
      let targetDatasetId = datasetId;
      if (creatingDataset) {
        const created = await api<{ dataset_id: string; name: string }>(
          "/api/v1/eval/datasets",
          {
            method: "POST",
            token: session.token,
            organizationId: session.organizationId,
            body: JSON.stringify({ name: newDatasetName.trim() }),
          },
        );
        targetDatasetId = created.dataset_id;
        setDatasetId(created.dataset_id);
      }
      const expectedSources = sources
        .split(/[;|]/)
        .map((value) => value.trim())
        .filter(Boolean);
      const example = {
        question: question.trim(),
        expected_answer: expectedAnswer.trim() || null,
        expected_behavior: behavior,
        expected_sources: expectedSources,
      };
      if (isEdit && caseId) {
        await api(`/api/v1/eval/datasets/${targetDatasetId}/examples/${caseId}`, {
          method: "PUT",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify(example),
        });
        setMsg("Caso actualizado.");
      } else {
        await api(`/api/v1/eval/datasets/${targetDatasetId}/examples`, {
          method: "POST",
          token: session.token,
          organizationId: session.organizationId,
          body: JSON.stringify({ examples: [example] }),
        });
        setMsg("Caso agregado. Ya cuenta para el próximo run.");
      }
      const target =
        datasets.find((ds) => ds.id === targetDatasetId) ||
        dataset ||
        { id: targetDatasetId, name: newDatasetName.trim() };
      onSaved?.(target);
      if (!onSaved) onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el caso");
    } finally {
      setBusy(false);
    }
  }

  async function onCsv(file: File) {
    if (!session || !datasetId || creatingDataset) return;
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
      title={isEdit ? "Editar caso de prueba" : "Agregar caso de prueba"}
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
            disabled={!question.trim() || (!dataset && !datasetId)}
          >
            {isEdit ? "Guardar cambios" : "Agregar caso"}
          </Button>
        </>
      }
    >
      <form id="eval-case-form" className="flex flex-col gap-4" onSubmit={onSubmit}>
        <ErrorInline message={error} className="mb-0" />
        <SuccessInline message={msg} className="mb-0" />

        {!dataset && !isEdit && (
          <Field
            label="Dataset"
            required
            hint="¿Todavía no tienes uno? Elige “Nuevo dataset” y se crea con este caso."
          >
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
              <option value={NEW_DATASET}>＋ Nuevo dataset</option>
            </Select>
          </Field>
        )}

        {creatingDataset && (
          <Field label="Nombre del nuevo dataset" required>
            <Input
              value={newDatasetName}
              onChange={(ev) => setNewDatasetName(ev.target.value)}
              placeholder="Preguntas de soporte ATPCO"
              autoComplete="off"
              required
            />
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

        {!isEdit && (
          <div className="border-t border-border-soft pt-3">
            <label className="flex items-center gap-2 text-[12.5px] text-muted">
              <UploadSimple size={15} aria-hidden />
              <span>O carga varios desde un CSV</span>
              <input
                type="file"
                accept=".csv,text/csv"
                className="block w-full cursor-pointer text-[12.5px] text-muted file:mr-3 file:cursor-pointer file:rounded-sm file:border file:border-border file:bg-raised file:px-3 file:py-1.5 file:text-[12.5px] file:font-medium file:text-text"
                disabled={busy || !datasetId || creatingDataset}
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
        )}
      </form>
    </Modal>
  );
}
