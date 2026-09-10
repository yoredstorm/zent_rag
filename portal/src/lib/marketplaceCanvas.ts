/** Tipos del canvas marketplace (Phase 33B) — drawer de instalación inline. */

export type ShopAction = {
  action_id: string;
  display_name: string;
  description?: string | null;
  cost: { model: string; price: number; currency: string };
};

export type ShopInstall = {
  slug: string;
  name: string;
  description: string;
  requires_credentials: boolean;
  requires_purpose?: boolean;
  actions: ShopAction[];
};

export type MarketRec = {
  install_id: string;
  reused: boolean;
  status: string;
  integration: { slug: string; name: string; actions: unknown[] };
};