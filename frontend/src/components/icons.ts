/**
 * Central re-export of every Lucide icon used in the app.
 *
 * Importing from one file keeps the icon vocabulary deliberate — adding a
 * new icon requires touching this file, which is the right friction.
 *
 * lucide-react@1.x ships pure ESM; tree-shaking works per-name.
 */

export {
  // Topbar / shell
  Search,
  Bell,
  LogOut,
  Settings,
  ChevronDown,

  // Sidebar
  Files,
  Share2,
  Clock,
  Trash2,
  ShieldCheck,
  HardDrive,
  Lock,

  // Breadcrumb
  ChevronRight,

  // File table
  FileText,
  FileImage,
  FileCode,
  FileArchive,
  File as FileGeneric,
  FileSpreadsheet,
  Folder,
  FolderOpen,
  Download,
  Eye,
  MoreHorizontal,
  Tag,
  History,
  RefreshCw,
  ArrowUpDown,
  RotateCcw,

  // Upload
  Upload,
  UploadCloud,
  X as Close,
  Plus,

  // Status / state
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Info,
} from "lucide-react";
