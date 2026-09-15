/**
 * Primitivas del design system de Zent.
 * Regla: usar estas antes que HTML suelto o clases ad-hoc.
 * Contrato completo en `.interface-design/system.md`.
 */

export { cn } from "./cn";
export { Button, ButtonLink, IconButton } from "./Button";
export type { ButtonProps, ButtonLinkProps, IconButtonProps, ButtonVariant, ButtonSize } from "./Button";
export { Badge, StatusBadge, StatusDot, statusLabel } from "./Badge";
export type { BadgeProps, StatusBadgeProps, Tone } from "./Badge";
export {
  Spinner,
  LoadingDots,
  Skeleton,
  SkeletonBlock,
  SkeletonTable,
  SkeletonCards,
  EmptyState,
  ErrorInline,
  SuccessInline,
  InfoInline,
  WarningInline,
  NoAccessState,
  OfflineState,
  Progress,
  StatusRow,
  PageSkeleton,
} from "./states";
export type { EmptyStateProps } from "./states";
export {
  Tooltip,
  Popover,
  Menu,
  MenuItem,
  MenuSeparator,
  MenuLabel,
  MenuCheckboxItem,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSub,
  MenuSubTrigger,
  MenuSubContent,
  menuItemClass,
  menuLabelClass,
  menuSeparatorClass,
  Modal,
  Drawer,
  ConfirmDialog,
} from "./overlay";
export type { TooltipProps, PopoverProps, MenuProps, ModalProps, DrawerProps, ConfirmDialogProps } from "./overlay";
export {
  Field,
  Input,
  Textarea,
  Select,
  PasswordInput,
  Checkbox,
  Switch,
  FormActions,
  SaveStatus,
} from "./form";
export type { FieldProps, InputProps, SelectProps, CheckboxProps, SaveState } from "./form";
export {
  Panel,
  PanelHeader,
  Section,
  SectionHeader,
  Breadcrumbs,
  PageHeader,
  Metric,
  MetricGrid,
  SplitPane,
  Toolbar,
  ToolbarSpacer,
  InlineFlash,
} from "./surface";
export type { BreadcrumbItem, MetricProps } from "./surface";
export { Tabs, TabsList, TabsTrigger, TabsContent } from "./tabs";
export type { TabsProps, TabsTriggerProps } from "./tabs";
export { CodeBlock, CopyButton, Kbd, KeyValue } from "./code";
export type { CodeBlockProps } from "./code";
export { DataTable, Pagination, ResultCount } from "./table";
export type { Column, DataTableProps, SortState, SortDir } from "./table";
