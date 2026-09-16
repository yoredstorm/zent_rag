/**
 * NotificationBuilder — "ENVIAR POR / DESTINATARIO / ASUNTO / MENSAJE".
 * Solo ofrece canales disponibles (endpoint notification-targets); para los
 * no conectados muestra el CTA "Conectar …". Escribe el mismo config que ya
 * ejecuta el nodo `notify`.
 */
import { PaperPlaneTilt, Plus, Trash, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import type { DataSourceOption } from "../../lib/dataPicker";
import { Button, ButtonLink, Input, Select, Textarea } from "../ui";
import { DataPicker } from "./DataPicker";

type ChannelOption = {
  value: string;
  label: string;
  available: boolean;
  requires: string | null;
  detail: string;
};

type PersonOption = { id: string; email: string; label: string };
type TeamOption = { id: string; label: string };

export type NotificationTargets = {
  channels: ChannelOption[];
  people: PersonOption[];
  teams: TeamOption[];
};

export type NotifyRecipient = {
  kind: "person" | "team" | "email" | "webhook";
  value: string;
  label?: string;
};

type Props = {
  config: Record<string, unknown>;
  dataSources: DataSourceOption[];
  onChange: (patch: Record<string, unknown>) => void;
  /** Targets precargados por el editor (evita fetch duplicado). */
  targets?: NotificationTargets | null;
};

export function NotificationBuilder({ config, dataSources, onChange, targets: providedTargets }: Props) {
  const { session } = useAuth();
  const [fetched, setFetched] = useState<NotificationTargets | null>(null);
  const [recipientKind, setRecipientKind] = useState<NotifyRecipient["kind"]>("person");
  const [recipientValue, setRecipientValue] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (providedTargets || !session) return;
    let alive = true;
    api<NotificationTargets>("/api/v1/workflows/notification-targets", {
      token: session.token,
      organizationId: session.organizationId,
    })
      .then((d) => {
        if (alive) setFetched(d);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [session, providedTargets]);

  const targets = providedTargets ?? fetched;
  const channel = String(config.channel ?? "in_app");
  const recipients: NotifyRecipient[] = Array.isArray(config.recipients)
    ? (config.recipients as NotifyRecipient[])
    : [];
  const messageValue = message ?? String(config.message ?? "");
  const unavailable = targets?.channels.filter((c) => !c.available) ?? [];

  function addRecipient() {
    const value = recipientValue.trim();
    if (!value) return;
    const label =
      recipientKind === "person"
        ? targets?.people.find((p) => p.id === value)?.label ?? value
        : recipientKind === "team"
          ? targets?.teams.find((t) => t.id === value)?.label ?? value
          : value;
    onChange({ recipients: [...recipients, { kind: recipientKind, value, label }] });
    setRecipientValue("");
  }

  function removeRecipient(index: number) {
    onChange({ recipients: recipients.filter((_, i) => i !== index) });
  }

  return (
    <div className="space-y-3" data-testid="wf-notification-builder">
      <div className="space-y-1.5">
        <label htmlFor="wf-notify-channel" className="text-[13px] font-medium text-text">
          Enviar por
        </label>
        <Select
          id="wf-notify-channel"
          value={channel}
          data-testid="wf-notify-channel"
          onChange={(e) => onChange({ channel: e.target.value })}
        >
          {(targets?.channels ?? [{ value: "in_app", label: "Zent", available: true, requires: null, detail: "" }]).map((c) => (
            <option key={c.value} value={c.value} disabled={!c.available}>
              {c.label}
              {!c.available ? " (no disponible)" : ""}
            </option>
          ))}
        </Select>
        {targets && (
          <p className="field-hint" data-testid="wf-notify-channel-detail">
            {targets.channels.find((c) => c.value === channel)?.detail}
          </p>
        )}
      </div>

      {unavailable.length > 0 && (
        <div className="space-y-1.5 rounded-md border border-border bg-soft/50 p-2.5" data-testid="wf-notify-unavailable">
          {unavailable.map((c) => (
            <div key={c.value} className="flex items-center gap-2 text-[11px]">
              <WarningCircle size={12} className="shrink-0 text-warn" aria-hidden />
              <span className="min-w-0 flex-1 truncate text-muted">{c.detail}</span>
              {c.requires && (
                <ButtonLink
                  to="/connectors"
                  variant="ghost"
                  size="sm"
                  className="shrink-0 text-[11px] text-accent"
                  data-testid={`wf-notify-connect-${c.value}`}
                >
                  Conectar {c.label}
                </ButtonLink>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="space-y-1.5">
        <span className="text-[13px] font-medium text-text">Destinatarios</span>
        {recipients.length > 0 && (
          <ul className="space-y-1" data-testid="wf-notify-recipients">
            {recipients.map((r, index) => (
              <li
                key={`${r.kind}-${r.value}-${index}`}
                className="flex items-center gap-2 rounded-sm bg-soft px-2 py-1.5 text-[12px]"
              >
                <span className="min-w-0 flex-1 truncate text-text">{r.label || r.value}</span>
                <span className="text-[10px] text-faint">
                  {r.kind === "person" ? "Persona" : r.kind === "team" ? "Equipo" : r.kind === "email" ? "Correo" : "Webhook"}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 min-h-0 px-0 text-danger"
                  aria-label={`Quitar ${r.label || r.value}`}
                  onClick={() => removeRecipient(index)}
                >
                  <Trash size={11} aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-center gap-1.5">
          <Select
            className="w-auto text-[12px]"
            value={recipientKind}
            data-testid="wf-notify-recipient-kind"
            aria-label="Tipo de destinatario"
            onChange={(e) => {
              setRecipientKind(e.target.value as NotifyRecipient["kind"]);
              setRecipientValue("");
            }}
          >
            <option value="person">Persona</option>
            <option value="team">Equipo</option>
            <option value="email">Correo</option>
            <option value="webhook">Webhook</option>
          </Select>

          {recipientKind === "person" ? (
            <Select
              className="min-w-0 flex-1 text-[12px]"
              value={recipientValue}
              data-testid="wf-notify-recipient-value"
              aria-label="Persona"
              onChange={(e) => setRecipientValue(e.target.value)}
            >
              <option value="">Elige una persona…</option>
              {(targets?.people ?? []).map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </Select>
          ) : recipientKind === "team" ? (
            <Select
              className="min-w-0 flex-1 text-[12px]"
              value={recipientValue}
              data-testid="wf-notify-recipient-value"
              aria-label="Equipo"
              onChange={(e) => setRecipientValue(e.target.value)}
            >
              <option value="">Elige un equipo…</option>
              {(targets?.teams ?? []).map((t) => (
                <option key={t.id} value={t.id}>{t.label}</option>
              ))}
            </Select>
          ) : (
            <Input
              className="min-w-0 flex-1 text-[12px]"
              placeholder={recipientKind === "email" ? "correo@empresa.com" : "https://…"}
              value={recipientValue}
              data-testid="wf-notify-recipient-value"
              aria-label={recipientKind === "email" ? "Correo" : "URL del webhook"}
              onChange={(e) => setRecipientValue(e.target.value)}
            />
          )}
          <Button
            variant="secondary"
            size="sm"
            leadingIcon={Plus}
            className="text-[11px]"
            data-testid="wf-notify-recipient-add"
            onClick={addRecipient}
            disabled={!recipientValue.trim()}
          >
            Añadir
          </Button>
        </div>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="wf-notify-subject" className="text-[13px] font-medium text-text">
          Asunto
        </label>
        <Input
          id="wf-notify-subject"
          placeholder="Stock bajo"
          value={String(config.title ?? "")}
          data-testid="wf-notify-subject"
          onChange={(e) => onChange({ title: e.target.value })}
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <label htmlFor="wf-notify-message" className="text-[13px] font-medium text-text">
            Mensaje
          </label>
          <span className="ml-auto">
            <DataPicker
              sources={dataSources}
              label="dato"
              testId="wf-notify-message-refs"
              onPick={(field) => {
                const next = messageValue ? `${messageValue} ${field.ref}` : field.ref;
                setMessage(next);
                onChange({ message: next });
              }}
            />
          </span>
        </div>
        <Textarea
          id="wf-notify-message"
          rows={3}
          placeholder="Producto: {{Producto → Nombre}} · Stock: {{Inventario → Stock}}"
          value={messageValue}
          data-testid="wf-notify-message"
          onChange={(e) => {
            setMessage(e.target.value);
            onChange({ message: e.target.value });
          }}
        />
      </div>

      <p className="flex items-center gap-1.5 text-[11px] text-faint">
        <PaperPlaneTilt size={11} aria-hidden /> En simulación no se envía nada: solo se listan los envíos.
      </p>
    </div>
  );
}
