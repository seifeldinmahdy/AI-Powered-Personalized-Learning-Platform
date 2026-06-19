import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import type { CSSProperties } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';
import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Code2,
  HelpCircle,
  Lightbulb,
  ListChecks,
  Loader2,
  MessageSquare,
  Pause,
  Play,
  RefreshCw,
  Save,
  Sparkles,
  StickyNote,
  Volume2,
  X,
} from 'lucide-react';
import { toast } from 'sonner';
import { Nova3DAvatar } from '../../components/Nova3DAvatar';
import { TypewriterLoader } from '../../components/personifai/TypewriterLoader';
import { getLesson } from '../../services/lessons';
import {
  generateCodingLab,
  explainLabCell,
  runLabCode,
  saveCellNote,
  saveGeneralNote,
  markQuestionAsked,
  completeLab,
  type CodingLabGenerateResponse,
  type LabCell,
  type LabSlideContext,
  type LabRunResponse,
  type SuggestedQuestion,
} from '../../services/codingLabs';
import type { BlendshapeData } from '../../services/tutor';


const LAB_STYLES = `.coding-lab-page {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  background: var(--bg-primary);
  color: var(--text-primary);
  --lab-surface: var(--bg-surface);
  --lab-text: var(--text-primary);
  --lab-muted-text: var(--text-secondary);
  --lab-border: var(--hairline);
  --lab-soft: var(--bg-surface);
  --lab-softer: var(--bg-paper-hover);
  --lab-primary: var(--accent-primary);
  --lab-primary-soft: color-mix(in oklab, var(--accent-primary) 12%, var(--bg-surface));
  --lab-on-primary: #ffffff;
  --lab-success: var(--accent-success);
  --lab-warning: #B45309;
  --lab-code-bg: var(--code-bg);
  --lab-code-text: #F3ECDF;
  --lab-shadow: rgba(19, 16, 13, 0.06);
}

.lab-header {
  position: sticky;
  top: 0;
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 24px;
  border-bottom: 1px solid var(--lab-border);
  background: color-mix(in oklab, var(--lab-surface) 94%, transparent);
  backdrop-filter: blur(12px);
}

.lab-header h1 {
  margin: 0;
  font-size: 20px;
  line-height: 1.25;
  font-weight: 800;
}

.lab-kicker {
  display: block;
  color: var(--text-secondary);
  color: var(--lab-muted-text);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0;
}

.lab-icon-button,
.lab-secondary-button,
.lab-finish-panel button,
.completion-card button {
  border: 1px solid var(--lab-border);
  background: var(--lab-surface);
  color: var(--lab-text);
  border-radius: 8px;
  cursor: pointer;
}

.lab-icon-button {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
}

.lab-header-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}

.lab-time {
  padding: 7px 10px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: color-mix(in oklab, var(--lab-success) 13%, var(--lab-surface));
  color: var(--lab-success);
  font-size: 13px;
  font-weight: 700;
}

.lab-secondary-button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 11px;
  font-size: 13px;
  font-weight: 700;
}

.lab-shell {
  display: grid;
  justify-content: center;
  width: 100%;
  max-width: 1540px;
  margin: 0 auto;
  padding: 24px 24px 56px;
}

.lab-main {
  width: 100%;
}

.lab-intro {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 18px;
  padding: 16px 18px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-surface);
}

.lab-intro p {
  flex: 1;
  margin: 0;
  color: var(--lab-muted-text);
  font-size: 15px;
}

.lab-guide-button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: 0 0 auto;
  min-height: 36px;
  padding: 8px 12px;
  border: 1px solid var(--lab-primary);
  border-radius: 8px;
  background: var(--lab-primary);
  color: var(--lab-on-primary);
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
}

.notebook {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.notebook-cell {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-surface);
  box-shadow: 0 8px 24px var(--lab-shadow);
  transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}

.notebook-cell.active {
  border-color: var(--lab-primary);
  box-shadow: 0 12px 34px color-mix(in oklab, var(--lab-primary) 22%, transparent);
}

.cell-gutter {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 18px 10px;
  border-right: 1px solid var(--lab-border);
  background: var(--lab-soft);
  color: var(--lab-muted-text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.cell-gutter button {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-surface);
  color: var(--lab-primary);
  cursor: pointer;
}

.cell-body {
  min-width: 0;
  padding: 18px;
}

.cell-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.cell-heading h2 {
  margin: 0;
  font-size: 17px;
  line-height: 1.35;
  font-weight: 800;
}

.cell-type {
  padding: 4px 8px;
  border-radius: 8px;
  background: var(--lab-primary-soft);
  color: var(--lab-primary);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.notebook-cell.task .cell-type {
  background: color-mix(in oklab, var(--lab-warning) 16%, var(--lab-surface));
  color: var(--lab-warning);
}

.notebook-cell.code .cell-type {
  background: color-mix(in oklab, var(--lab-success) 13%, var(--lab-surface));
  color: var(--lab-success);
}

.cell-narrative,
.task-prompt {
  margin: 0 0 14px;
  color: var(--lab-text);
  font-size: 15px;
  line-height: 1.65;
}

.code-block,
.cell-output pre,
.task-cell textarea {
  width: 100%;
  border-radius: 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  line-height: 1.55;
}

.code-block {
  overflow-x: auto;
  margin: 0;
  padding: 16px;
  background: var(--lab-code-bg);
  color: var(--lab-code-text);
}

.cell-output {
  margin-top: 12px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-soft);
}

.cell-output span {
  display: block;
  padding: 8px 12px;
  border-bottom: 1px solid var(--lab-border);
  color: var(--lab-muted-text);
  font-size: 12px;
  font-weight: 800;
}

.cell-output pre {
  margin: 0;
  padding: 12px;
  white-space: pre-wrap;
}

.task-cell textarea {
  min-height: 180px;
  padding: 14px;
  border: 1px solid var(--lab-border);
  outline: none;
  resize: vertical;
  background: var(--lab-code-bg);
  color: var(--lab-code-text);
}

.task-cell textarea:focus {
  border-color: var(--lab-primary);
  box-shadow: 0 0 0 3px color-mix(in oklab, var(--lab-primary) 20%, transparent);
}

.criteria {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-soft);
}

.criteria h3 {
  margin: 0 0 8px;
  color: var(--lab-muted-text);
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}

.criterion {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  color: var(--lab-text);
  font-size: 13px;
}

.criterion+.criterion {
  margin-top: 7px;
}

.criterion svg {
  color: var(--lab-success);
  margin-top: 2px;
}

.tips {
  margin-top: 12px;
  padding: 12px;
  border-left: 3px solid var(--lab-warning);
  border-radius: 8px;
  background: color-mix(in oklab, var(--lab-warning) 14%, var(--lab-surface));
  color: color-mix(in oklab, var(--lab-warning) 70%, var(--lab-text));
}

.tips p {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
}

.tips p+p {
  margin-top: 6px;
}

.task-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
}

.task-actions button,
.lab-tutor-controls button,
.lab-finish-panel button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 38px;
  padding: 8px 12px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-surface);
  color: var(--lab-text);
  font-size: 13px;
  font-weight: 800;
  cursor: pointer;
}

.task-actions button.primary,
.lab-finish-panel button,
.completion-card button {
  border-color: var(--lab-primary);
  background: var(--lab-primary);
  color: var(--lab-on-primary);
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.52;
}

.lab-sidebar {
  position: sticky;
  top: 88px;
  align-self: start;
}

.lab-checklist {
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-surface);
  box-shadow: 0 8px 24px var(--lab-shadow);
  overflow: hidden;
}

.checklist-title {
  display: flex;
  gap: 10px;
  padding: 16px;
  border-bottom: 1px solid var(--lab-border);
  background: var(--lab-soft);
}

.checklist-title h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
}

.checklist-title p {
  margin: 2px 0 0;
  color: var(--lab-muted-text);
  font-size: 12px;
}

.checklist-item {
  display: flex;
  gap: 10px;
  padding: 13px 16px;
  border-bottom: 1px solid var(--lab-border);
}

.checklist-item:last-child {
  border-bottom: 0;
}

.checklist-item svg {
  flex: 0 0 auto;
  color: var(--lab-success);
  margin-top: 2px;
}

.checklist-item strong {
  display: block;
  color: var(--lab-text);
  font-size: 13px;
  line-height: 1.45;
}

.checklist-item span {
  display: block;
  margin-top: 3px;
  color: var(--lab-muted-text);
  font-size: 12px;
  line-height: 1.45;
}

.lab-checklist-mobile {
  display: none;
  margin-bottom: 16px;
}

.lab-tutor-bubble {
  position: fixed;
  right: auto;
  z-index: 30;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 340px;
  pointer-events: none;
  transition: top 420ms cubic-bezier(0.22, 1, 0.36, 1), left 420ms cubic-bezier(0.22, 1, 0.36, 1), transform 180ms ease;
}

.lab-tutor-bubble.speaking {
  transform: translateY(-2px);
}

.lab-tutor-avatar {
  flex: 0 0 auto;
  border: 3px solid var(--lab-surface);
  border-radius: 999px;
  background: linear-gradient(135deg, #4c6fff, #10b981);
  box-shadow: 0 14px 30px color-mix(in oklab, var(--text-primary) 18%, transparent);
}

.lab-tutor-bubble.speaking .lab-tutor-avatar {
  animation: lab-tutor-speak 1.2s ease-in-out infinite;
}

.lab-tutor-bubble.speaking .lab-tutor-body {
  border-color: var(--lab-primary);
}

.lab-tutor-body {
  pointer-events: auto;
  padding: 12px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: color-mix(in oklab, var(--lab-surface) 96%, transparent);
  box-shadow: 0 16px 40px color-mix(in oklab, var(--text-primary) 16%, transparent);
}

.lab-tutor-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--lab-primary);
  font-size: 13px;
  font-weight: 900;
}

.lab-tutor-body p {
  margin: 7px 0 10px;
  color: var(--lab-text);
  font-size: 13px;
  line-height: 1.5;
}

.lab-tutor-controls {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.lab-tutor-controls button {
  min-height: 30px;
  padding: 5px 9px;
  font-size: 12px;
}

.lab-finish-panel {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  padding: 18px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-surface);
}

.lab-run-output {
  margin-top: 12px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  overflow: hidden;
  background: var(--lab-soft);
}

.lab-run-output.success {
  border-color: color-mix(in oklab, var(--lab-success) 55%, var(--lab-border));
}

.lab-run-output.error {
  border-color: color-mix(in oklab, var(--error-red) 55%, var(--lab-border));
}

.lab-run-output span {
  display: block;
  padding: 8px 12px;
  border-bottom: 1px solid var(--lab-border);
  color: var(--lab-muted-text);
  font-size: 12px;
  font-weight: 800;
}

.lab-run-output pre {
  margin: 0;
  padding: 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  color: var(--lab-text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  line-height: 1.55;
}

.lab-finish-panel h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
}

.lab-finish-panel p {
  margin: 4px 0 0;
  color: var(--lab-muted-text);
  font-size: 14px;
}

.lab-loading,
.lab-error {
  display: grid;
  min-height: 100vh;
  place-items: center;
  background: var(--bg-primary);
}

.lab-loading-panel,
.lab-error-panel {
  width: min(460px, calc(100vw - 32px));
  padding: 30px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-surface);
  text-align: center;
  box-shadow: 0 18px 50px var(--lab-shadow);
}

.lab-loading-panel h1,
.lab-error-panel h1 {
  margin: 16px 0 8px;
  font-size: 24px;
  font-weight: 900;
}

.lab-loading-panel p,
.lab-error-panel p {
  margin: 0;
  color: var(--text-secondary);
}

.lab-spin {
  color: var(--lab-primary);
  animation: lab-spin 900ms linear infinite;
}

.lab-loading-steps {
  display: flex;
  justify-content: center;
  gap: 7px;
  margin-top: 20px;
}

.lab-loading-steps span {
  width: 26px;
  height: 4px;
  border-radius: 999px;
  background: var(--lab-border);
}

.lab-loading-steps span.active {
  background: var(--lab-primary);
}

.lab-error-panel button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-top: 18px;
  padding: 10px 14px;
  border: 1px solid var(--lab-primary);
  border-radius: 8px;
  background: var(--lab-primary);
  color: var(--lab-on-primary);
  font-weight: 800;
  cursor: pointer;
}

.completion-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: grid;
  place-items: center;
  background: color-mix(in oklab, var(--text-primary) 58%, transparent);
  backdrop-filter: blur(7px);
}

.completion-card {
  width: min(430px, calc(100vw - 32px));
  padding: 30px;
  border-radius: 8px;
  background: var(--lab-surface);
  text-align: center;
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.26);
  animation: lab-pop 420ms ease both;
}

.completion-ring {
  display: grid;
  width: 112px;
  height: 112px;
  margin: 0 auto 16px;
  place-items: center;
  border: 8px solid color-mix(in oklab, var(--lab-success) 20%, var(--lab-surface));
  border-radius: 999px;
  color: var(--lab-success);
  animation: lab-ring 900ms ease both;
}

.completion-card h2 {
  margin: 0;
  font-size: 25px;
  font-weight: 900;
}

.completion-card p {
  margin: 10px 0 20px;
  color: var(--lab-muted-text);
}

.completion-card button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  font-weight: 900;
  cursor: pointer;
}

@keyframes lab-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes lab-pop {
  from {
    opacity: 0;
    transform: translateY(18px) scale(0.96);
  }

  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes lab-ring {
  0% {
    transform: scale(0.55);
    opacity: 0;
  }

  70% {
    transform: scale(1.08);
    opacity: 1;
  }

  100% {
    transform: scale(1);
  }
}

@keyframes lab-tutor-speak {

  0%,
  100% {
    transform: translateY(0) scale(1);
  }

  50% {
    transform: translateY(-5px) scale(1.025);
  }
}

@media (max-width: 1180px) {
  .lab-shell {
    grid-template-columns: 1fr;
  }

  .lab-sidebar {
    display: none;
  }

  .lab-checklist-mobile {
    display: block;
  }

  .lab-tutor-bubble {
    right: 20px;
    width: min(330px, calc(100vw - 40px));
  }
}

@media (max-width: 760px) {
  .lab-header {
    align-items: flex-start;
    padding: 12px;
  }

  .lab-header-actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    max-width: 180px;
  }

  .lab-shell {
    padding: 14px 12px 130px;
  }

  .notebook-cell {
    grid-template-columns: 44px minmax(0, 1fr);
  }

  .cell-gutter {
    padding: 14px 6px;
  }

  .cell-body {
    padding: 14px;
  }

  .cell-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }

  .lab-tutor-bubble {
    left: 12px;
    right: 12px;
    bottom: 12px;
    top: auto !important;
    width: auto;
    align-items: center;
  }

  .lab-tutor-avatar {
    display: none;
  }

  .lab-intro {
    flex-direction: column;
  }

  .lab-guide-button {
    width: 100%;
    justify-content: center;
  }

  .task-actions,
  .lab-finish-panel {
    align-items: stretch;
    flex-direction: column;
  }
}

/* ── Cell notes ────────────────────────────────────────────────── */

.cell-notes {
  margin-top: 12px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  overflow: hidden;
}

.cell-notes-toggle {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 10px 12px;
  border: none;
  background: var(--lab-softer);
  color: var(--lab-muted-text);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  cursor: pointer;
  transition: background 150ms ease;
}

.cell-notes-toggle:hover {
  background: var(--lab-soft);
}

.cell-notes-toggle svg:last-child {
  margin-left: auto;
  transition: transform 200ms ease;
}

.cell-notes-toggle.open svg:last-child {
  transform: rotate(180deg);
}

.cell-notes-body {
  padding: 12px;
  border-top: 1px solid var(--lab-border);
  background: var(--lab-surface);
}

.cell-notes-saved {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 6px;
  color: var(--lab-success);
  font-size: 11px;
  font-weight: 700;
  opacity: 0;
  transition: opacity 300ms ease;
}

.cell-notes-saved.visible {
  opacity: 1;
}

.cell-notes-list {
  margin: 0 0 10px;
  padding: 0;
  list-style: none;
}

.cell-notes-list li {
  padding: 6px 8px;
  margin-bottom: 4px;
  border-radius: 6px;
  background: var(--lab-softer);
  color: var(--lab-text);
  font-size: 13px;
  line-height: 1.5;
}

.cell-notes textarea {
  width: 100%;
  min-height: 60px;
  padding: 10px;
  border: 1px solid var(--lab-border);
  border-radius: 6px;
  background: var(--lab-code-bg);
  color: var(--lab-code-text);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.5;
  resize: vertical;
  outline: none;
}

.cell-notes textarea:focus {
  border-color: var(--lab-primary);
  box-shadow: 0 0 0 3px color-mix(in oklab, var(--lab-primary) 18%, transparent);
}

/* ── Cell row layout (cell + questions side by side) ──────────── */

.cell-row {
  display: grid;
  grid-template-columns: 340px minmax(0, 800px) 340px;
  justify-content: center;
  gap: 24px;
  margin-bottom: 24px;
}

.cell-row > .notebook-cell {
  grid-column: 2;
  grid-row: 1;
  min-width: 0;
}

.sq-box {
  width: 240px;
  height: max-content;
  border: 1px solid var(--lab-border);
  border-radius: 10px;
  background: var(--lab-surface);
  overflow: hidden;
  z-index: 10;
  grid-row: 1;
}

/* When tutor is on the right, sq-box is on the left (col 1) */
.cell-row.tutor-right .sq-box {
  grid-column: 1;
  justify-self: end;
}

/* When tutor is on the left, sq-box is on the right (col 3) */
.cell-row.tutor-left .sq-box {
  grid-column: 3;
  justify-self: start;
}

.sq-box-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--lab-border);
  background: var(--lab-soft);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  color: var(--lab-muted-text);
  letter-spacing: 0.4px;
}

.sq-box-header svg {
  color: var(--lab-primary);
}

.sq-box-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
}

.sq-chip {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 10px;
  border: 1px solid color-mix(in oklab, var(--lab-primary) 25%, var(--lab-border));
  border-radius: 8px;
  background: color-mix(in oklab, var(--lab-primary) 5%, var(--lab-surface));
  color: var(--lab-text);
  font-size: 12px;
  line-height: 1.4;
  text-align: left;
  cursor: pointer;
  transition: all 160ms ease;
}

.sq-chip:hover {
  border-color: var(--lab-primary);
  background: color-mix(in oklab, var(--lab-primary) 14%, var(--lab-surface));
  box-shadow: 0 2px 8px color-mix(in oklab, var(--lab-primary) 12%, transparent);
}

.sq-chip.asked {
  opacity: 0.5;
  border-color: var(--lab-border);
  background: var(--lab-softer);
  cursor: default;
  text-decoration: line-through;
}

.sq-chip.asked:hover {
  box-shadow: none;
}

.sq-chip svg {
  flex: 0 0 auto;
  margin-top: 1px;
  color: var(--lab-primary);
}

.sq-chip.asked svg {
  color: var(--lab-muted-text);
}

@media (max-width: 1200px) {
  .cell-row, .cell-row.tutor-right, .cell-row.tutor-left {
    display: flex;
    flex-direction: column;
  }
  .cell-row > .notebook-cell {
    width: 100%;
  }
  .sq-box {
    width: 100%;
    margin-top: 16px;
  }
}

/* ── Global notepad ────────────────────────────────────────────── */

.notepad-fab {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 50;
  display: grid;
  width: 52px;
  height: 52px;
  place-items: center;
  border: 2px solid var(--lab-primary);
  border-radius: 999px;
  background: var(--lab-primary);
  color: var(--lab-on-primary);
  cursor: pointer;
  box-shadow: 0 8px 28px color-mix(in oklab, var(--lab-primary) 35%, transparent);
  transition: transform 180ms ease, box-shadow 180ms ease;
}

.notepad-fab:hover {
  transform: scale(1.08);
  box-shadow: 0 12px 36px color-mix(in oklab, var(--lab-primary) 45%, transparent);
}

.notepad-badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--error-red);
  color: white;
  font-size: 10px;
  font-weight: 800;
  line-height: 18px;
  text-align: center;
}

.notepad-panel {
  z-index: 50;
  width: 280px;
  max-height: 340px;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--lab-border);
  border-radius: 12px;
  background: var(--lab-surface);
  box-shadow: 0 20px 60px color-mix(in oklab, var(--text-primary) 22%, transparent);
  animation: lab-pop 280ms ease both;
  user-select: none;
}

.notepad-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--lab-border);
  background: var(--lab-soft);
  border-radius: 12px 12px 0 0;
}

.notepad-header h3 {
  margin: 0;
  flex: 1;
  font-size: 14px;
  font-weight: 800;
}

.notepad-header button {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 1px solid var(--lab-border);
  border-radius: 6px;
  background: var(--lab-surface);
  color: var(--lab-muted-text);
  cursor: pointer;
}

.notepad-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.notepad-body textarea {
  width: 100%;
  min-height: 80px;
  padding: 10px;
  border: 1px solid var(--lab-border);
  border-radius: 8px;
  background: var(--lab-code-bg);
  color: var(--lab-code-text);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.5;
  resize: vertical;
  outline: none;
}

.notepad-body textarea:focus {
  border-color: var(--lab-primary);
  box-shadow: 0 0 0 3px color-mix(in oklab, var(--lab-primary) 18%, transparent);
}

.notepad-notes-list {
  margin: 0 0 10px;
  padding: 0;
  list-style: none;
}

.notepad-notes-list li {
  padding: 8px 10px;
  margin-bottom: 6px;
  border-radius: 6px;
  background: var(--lab-softer);
  color: var(--lab-text);
  font-size: 13px;
  line-height: 1.5;
}

.notepad-saved {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 6px;
  color: var(--lab-success);
  font-size: 11px;
  font-weight: 700;
  opacity: 0;
  transition: opacity 300ms ease;
}

.notepad-saved.visible {
  opacity: 1;
}

@media (max-width: 760px) {
  .notepad-panel {
    width: calc(100vw - 24px) !important;
    max-height: 360px;
  }
  .notepad-fab {
    right: 12px;
    bottom: 12px;
  }
}

/* ── Codex design-language layer ───────────────────────────────────
   Brings the lab onto the student "codex" system to match LiveSession:
   editorial display headings (Space Grotesk), mono uppercase labels
   (JetBrains Mono) and ink-black / ghost buttons. The floating tutor
   bubble + avatar (.lab-tutor-*) are intentionally left untouched. */

.coding-lab-page { font-family: var(--ff-body); }

/* Display headings */
.coding-lab-page .lab-header h1,
.coding-lab-page .cell-heading h2,
.coding-lab-page .lab-finish-panel h2,
.coding-lab-page .completion-card h2,
.coding-lab-page .checklist-title h2,
.coding-lab-page .lab-error-panel h1,
.coding-lab-page .notepad-header h3 {
  font-family: var(--ff-display);
  font-weight: 700;
  letter-spacing: -0.02em;
}

/* Mono uppercase labels / eyebrows */
.coding-lab-page .lab-kicker,
.coding-lab-page .cell-type,
.coding-lab-page .criteria h3,
.coding-lab-page .sq-box-header,
.coding-lab-page .cell-notes-toggle,
.coding-lab-page .cell-output span,
.coding-lab-page .lab-run-output span,
.coding-lab-page .lab-time {
  font-family: var(--ff-mono);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

/* Buttons → codex. Primary = ink-black on paper; secondary = ghost with
   a steel hairline. Tutor controls (.lab-tutor-controls button) excluded. */
.coding-lab-page .lab-secondary-button,
.coding-lab-page .lab-icon-button,
.coding-lab-page .task-actions button,
.coding-lab-page .lab-finish-panel button,
.coding-lab-page .completion-card button,
.coding-lab-page .lab-guide-button,
.coding-lab-page .lab-error-panel button {
  font-family: var(--ff-mono);
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  border-radius: var(--radius-md);
  transition: transform 120ms ease, background 160ms ease, border-color 160ms ease;
}

.coding-lab-page .lab-secondary-button:active,
.coding-lab-page .lab-icon-button:active,
.coding-lab-page .task-actions button:active,
.coding-lab-page .lab-finish-panel button:active,
.coding-lab-page .completion-card button:active,
.coding-lab-page .lab-guide-button:active { transform: scale(0.97); }

/* Primary actions → ink-black */
.coding-lab-page .task-actions button.primary,
.coding-lab-page .lab-finish-panel button,
.coding-lab-page .completion-card button,
.coding-lab-page .lab-guide-button,
.coding-lab-page .lab-error-panel button {
  background: var(--ink-black);
  border-color: var(--ink-black);
  color: var(--bg-paper);
}

/* Secondary / ghost → transparent with a steel hairline */
.coding-lab-page .lab-secondary-button,
.coding-lab-page .lab-icon-button,
.coding-lab-page .task-actions button:not(.primary) {
  background: transparent;
  border-color: var(--steel);
  color: var(--text-primary);
}

.coding-lab-page .lab-secondary-button:hover,
.coding-lab-page .lab-icon-button:hover,
.coding-lab-page .task-actions button:not(.primary):hover {
  background: var(--bg-paper-hover);
  border-color: var(--text-primary);
}`;

interface LocationState {
  nextLessonId?: number | string | null;
  courseId?: string;
  lessonTitle?: string;
  sessionTitle?: string;
  sessionId?: string;
  studentProfileSummary?: string;
  slides?: LabSlideContext[];
}

const LOADING_STEPS = [
  'Reading the session summary',
  'Building the lab checklist',
  'Generating notebook cells',
  'Adding tutor tips',
  'Preparing your practice tasks',
];

function getStudentId(): string {
  try {
    const authUser = localStorage.getItem('auth_user');
    if (!authUser) return 'anonymous';
    const parsed = JSON.parse(authUser);
    return String(parsed.id ?? 'anonymous');
  } catch {
    return 'anonymous';
  }
}

function contentToText(value: unknown): string {
  if (!value) return '';
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    return value.map(contentToText).filter(Boolean).join('\n');
  }
  if (typeof value === 'object') {
    const data = value as Record<string, unknown>;
    const preferred = [
      data.title,
      data.text,
      data.content,
      data.body,
      data.body_content,
      data.items,
    ];
    return preferred.map(contentToText).filter(Boolean).join('\n');
  }
  return String(value);
}

function codeFor(cell: LabCell): string {
  return cell.cell_type === 'task'
    ? cell.starter_code || '# Write your code here'
    : cell.code || '';
}

function isTask(cell: LabCell): boolean {
  return cell.cell_type === 'task';
}

export default function CodingLab() {
  const { courseId, sessionNumber } = useParams<{ courseId: string; sessionNumber: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const state = (location.state as LocationState) ?? {};

  const resolvedCourseId = courseId ?? state.courseId ?? '';
  const resolvedSessionId = sessionNumber ?? '';
  const [labResponse, setLabResponse] = useState<CodingLabGenerateResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeCell, setActiveCell] = useState(0);
  const [taskCode, setTaskCode] = useState<Record<string, string>>({});
  const [completedTasks, setCompletedTasks] = useState<Set<string>>(new Set());
  const [tipIndex, setTipIndex] = useState<Record<string, number>>({});
  const [showCompletion, setShowCompletion] = useState(false);
  const [bubblePosition, setBubblePosition] = useState({ top: 140, left: 900 });
  const [bubbleText, setBubbleText] = useState('');
  const [isNarrating, setIsNarrating] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [isInitialPositioned, setIsInitialPositioned] = useState(false);
  const [narrationSide, setNarrationSide] = useState<'left' | 'right'>('right');
  const [blendshapes, setBlendshapes] = useState<BlendshapeData | null>(null);
  const [narratingCellId, setNarratingCellId] = useState<string | null>(null);
  const [runResults, setRunResults] = useState<Record<string, LabRunResponse>>({});
  const [runningCellId, setRunningCellId] = useState<string | null>(null);

  // Notes, questions, notepad
  const [cellNoteText, setCellNoteText] = useState<Record<string, string>>({});
  const [cellNoteOpen, setCellNoteOpen] = useState<Record<string, boolean>>({});
  const [cellNoteSaved, setCellNoteSaved] = useState<Record<string, boolean>>({});
  const [generalNoteText, setGeneralNoteText] = useState('');
  const [generalNoteSaved, setGeneralNoteSaved] = useState(false);
  const [notepadOpen, setNotepadOpen] = useState(false);
  const [askedQuestions, setAskedQuestions] = useState<Set<string>>(new Set());
  const [sqBoxOpen, setSqBoxOpen] = useState<Record<string, boolean>>({});
  const [fabPos, setFabPos] = useState({ x: -1, y: -1 });

  const cellRefs = useRef<Array<HTMLDivElement | null>>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const narrationTokenRef = useRef(0);
  const isPausedRef = useRef(false);
  const hasSwappedRef = useRef(false);
  const notepadRef = useRef<HTMLDivElement | null>(null);
  const fabRef = useRef<HTMLDivElement | null>(null);
  const dragFabRef = useRef<{ dragging: boolean; offsetX: number; offsetY: number }>({ dragging: false, offsetX: 0, offsetY: 0 });
  const dragMovedRef = useRef(false);

  // Initialize widget position on first render
  useEffect(() => {
    if (fabPos.x === -1) {
      setFabPos({ x: window.innerWidth - 76, y: window.innerHeight - 76 });
    }
  }, []);

  // When opening notepad, check bounds so the panel doesn't render off-screen
  useEffect(() => {
    if (notepadOpen && fabRef.current && notepadRef.current) {
      const fabRect = fabRef.current.getBoundingClientRect();
      const panelRect = notepadRef.current.getBoundingClientRect();
      let { x, y } = fabPos;
      let changed = false;

      // The panel extends above the FAB by panelRect.height + 16px
      if (y - panelRect.height - 16 < 60) {
        y = 60 + panelRect.height + 16;
        changed = true;
      }
      // The panel extends to the left of the FAB by panelRect.width - fabRect.width
      if (x - (panelRect.width - fabRect.width) < 16) {
        x = panelRect.width - fabRect.width + 16;
        changed = true;
      }

      if (changed) {
        setFabPos({ x, y });
      }
    }
  }, [notepadOpen, fabPos.x, fabPos.y]);

  // Drag handler for the unified widget
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (dragFabRef.current.dragging && fabRef.current) {
        e.preventDefault();
        dragMovedRef.current = true; // flag that we actually moved, so click won't trigger open
        const fabW = fabRef.current.offsetWidth;
        const fabH = fabRef.current.offsetHeight;
        const headerH = 60;
        let newX = e.clientX - dragFabRef.current.offsetX;
        let newY = e.clientY - dragFabRef.current.offsetY;

        let boundsTopOffset = 0;
        let boundsLeftOffset = 0;
        if (notepadOpen && notepadRef.current) {
          const panelRect = notepadRef.current.getBoundingClientRect();
          boundsTopOffset = panelRect.height + 16;
          boundsLeftOffset = panelRect.width - fabW;
        }

        newX = Math.max(boundsLeftOffset, Math.min(newX, window.innerWidth - fabW - 16));
        newY = Math.max(headerH + boundsTopOffset, Math.min(newY, window.innerHeight - fabH - 16));

        setFabPos({ x: newX, y: newY });
      }
    };
    const handleMouseUp = () => {
      dragFabRef.current.dragging = false;
    };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [notepadOpen]);

  async function buildFallbackSlides(): Promise<{ lessonTitle: string; slides: LabSlideContext[] }> {
    return { lessonTitle: state.lessonTitle || state.sessionTitle || 'Session', slides: state.slides || [] };
  }

  async function loadLab(force = false) {
    if (!resolvedCourseId || !resolvedSessionId) {
      setError('Missing course or session information.');
      setLoading(false);
      return;
    }

    setLoading(true);
    setError('');
    try {
      const fallback = await buildFallbackSlides();
      const lessonTitle = state.sessionTitle || state.lessonTitle || fallback.lessonTitle;
      const slides = state.slides && state.slides.length > 0 ? state.slides : fallback.slides;
      const response = await generateCodingLab({
        student_id: getStudentId(),
        course_id: String(resolvedCourseId),
        lesson_id: String(resolvedSessionId),
        session_id: state.sessionId || resolvedSessionId,
        lesson_title: lessonTitle,
        student_profile_summary: state.studentProfileSummary || '',
        slides,
        force_regenerate: force,
      });
      setLabResponse(response);
      setTaskCode(
        response.lab.cells.reduce<Record<string, string>>((acc, cell) => {
          if (isTask(cell)) acc[cell.id] = codeFor(cell);
          return acc;
        }, {}),
      );
      setCompletedTasks(new Set());
      setTipIndex({});
      setActiveCell(0);
      setIsInitialPositioned(false);
      setNarrationSide('right');
      hasSwappedRef.current = false;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not generate the coding lab.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadLab(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedCourseId, resolvedSessionId]);

  const lab = labResponse?.lab;
  const taskCells = useMemo(() => lab?.cells.filter(isTask) ?? [], [lab]);
  const allTasksDone = taskCells.length === 0 || taskCells.every((cell) => completedTasks.has(cell.id));

  useEffect(() => {
    setNarrationSide(activeCell % 2 === 0 ? 'right' : 'left');
    hasSwappedRef.current = false;
  }, [activeCell]);

  useEffect(() => {
    const update = () => {
      const node = cellRefs.current[activeCell];
      if (!node) return;
      const rect = node.getBoundingClientRect();
      const bubbleWidth = 340;
      const gap = 24;
      const top = Math.max(96, Math.min(window.innerHeight - 280, rect.top + 12));

      // The grid layout ensures there is a wide empty column precisely where the tutor goes
      let left = narrationSide === 'right'
        ? rect.right + gap
        : rect.left - bubbleWidth - gap;

      // Keep it on-screen if the viewport is narrow
      left = Math.max(16, Math.min(left, window.innerWidth - bubbleWidth - 16));

      setBubblePosition({ top, left });

      if (!isInitialPositioned) {
        setTimeout(() => setIsInitialPositioned(true), 50);
      }
    };
    update();
    window.addEventListener('scroll', update, true);
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
    };
  }, [activeCell, lab, narrationSide, isInitialPositioned]);

  function goToCell(index: number, force = false) {
    if (!force && index > activeCell) {
      const currentCell = lab?.cells[activeCell];
      if (currentCell?.cell_type === 'task' && !completedTasks.has(currentCell.id)) {
        toast.error('Please complete the current task before moving on.');
        return false;
      }
    }
    const bounded = Math.max(0, Math.min(index, (lab?.cells.length ?? 1) - 1));
    setActiveCell(bounded);
    cellRefs.current[bounded]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return true;
  }

  function setAudioBase64(base64: string) {
    const audio = audioRef.current;
    if (!audio) return;
    audio.src = `data:audio/mpeg;base64,${base64}`;
    setIsPaused(false);
    isPausedRef.current = false;
    audio.play().then(() => setIsNarrating(true)).catch(() => {
      setIsNarrating(false);
      toast.error('Click Start narration again if your browser blocked audio.');
    });
  }

  const handlePlayPause = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPausedRef.current) {
      audio.play().catch(() => { });
      isPausedRef.current = false;
      setIsPaused(false);
      setIsNarrating(true);
    } else {
      audio.pause();
      isPausedRef.current = true;
      setIsPaused(true);
      setIsNarrating(false);
    }
  };

  async function explainCell(index: number, mode: 'explain' | 'tip' = 'explain', force = false) {
    if (!lab) return;
    const bounded = Math.max(0, Math.min(index, lab.cells.length - 1));
    const cell = lab.cells[bounded];
    const canGo = goToCell(bounded, force);
    if (!canGo) return;

    const token = ++narrationTokenRef.current;
    setNarratingCellId(cell.id);
    setIsNarrating(true);
    setIsPaused(false);
    isPausedRef.current = false;
    hasSwappedRef.current = false;
    setBlendshapes(null);
    setBubbleText(mode === 'tip' ? 'Thinking of a useful hint...' : 'Preparing a spoken explanation...');

    try {
      const response = await explainLabCell({
        session_id: state.sessionId,
        lab_title: lab.title,
        cell,
        mode,
        student_profile_summary: state.studentProfileSummary || '',
      });
      if (token !== narrationTokenRef.current) return;
      setBubbleText(response.text);
      setBlendshapes(response.blendshapes || null);
      if (response.audio_base64) {
        setAudioBase64(response.audio_base64);
      } else {
        setIsNarrating(false);
        toast.error('The tutor generated text but audio was unavailable.');
      }
    } catch (err) {
      setIsNarrating(false);
      toast.error(err instanceof Error ? err.message : 'Could not explain this lab cell.');
    }
  }

  async function runCell(cell: LabCell) {
    const code = cell.cell_type === 'task' ? taskCode[cell.id] || codeFor(cell) : cell.code || '';
    if (!code.trim()) {
      toast.error('No code in this cell to run.');
      return;
    }
    setRunningCellId(cell.id);
    try {
      const result = await runLabCode(code);
      setRunResults((prev) => ({ ...prev, [cell.id]: result }));
      if (result.success) toast.success('Code ran successfully.');
      else toast.error('Code ran with an error.');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not run this code.');
    } finally {
      setRunningCellId(null);
    }
  }

  function markTaskDone(cell: LabCell) {
    const current = (taskCode[cell.id] || '').trim();
    const starter = (cell.starter_code || '').trim();
    if (!current || current === starter) {
      toast.error('Change the starter code before marking this task complete.');
      return;
    }
    setCompletedTasks((prev) => new Set([...prev, cell.id]));
    toast.success('Task marked complete.');
    const nextIndex = Math.min(activeCell + 1, (lab?.cells.length ?? 1) - 1);

    if (nextIndex > activeCell) {
      explainCell(nextIndex, 'explain', true);
    } else {
      goToCell(nextIndex, true);
      if (audioRef.current) {
        audioRef.current.pause();
        setIsNarrating(false);
        setIsPaused(false);
      }
    }
  }

  function showNextTip(cell: LabCell, index: number) {
    const tips = cell.tips || [];
    if (tips.length === 0) return;
    const currentTipIndex = tipIndex[cell.id] ?? 0;
    const tip = tips[Math.min(currentTipIndex, tips.length - 1)];
    setTipIndex((prev) => ({
      ...prev,
      [cell.id]: Math.min(currentTipIndex + 1, tips.length),
    }));
    goToCell(index);
    setBubbleText(tip);
    explainCell(index, 'tip');
  }

  function finishLab() {
    if (!allTasksDone) {
      toast.error('Finish the lab tasks first. The tutor left tips beside each task.');
      return;
    }
    setShowCompletion(true);
  }

  // ── Notes & questions handlers ────────────────────────────────

  const handleCellNoteBlur = useCallback((cellId: string) => {
    const text = (cellNoteText[cellId] || '').trim();
    if (!text || !labResponse) return;
    saveCellNote(labResponse.lab_id, cellId, text, getStudentId()).catch(() => { });

    setLabResponse((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        lab: {
          ...prev.lab,
          cells: prev.lab.cells.map((c) =>
            c.id === cellId
              ? { ...c, student_notes: [...(c.student_notes || []), { content: text }] }
              : c
          ),
        },
      };
    });

    setCellNoteSaved((prev) => ({ ...prev, [cellId]: true }));
    setTimeout(() => setCellNoteSaved((prev) => ({ ...prev, [cellId]: false })), 2000);
    setCellNoteText((prev) => ({ ...prev, [cellId]: '' }));
  }, [cellNoteText, labResponse]);

  const handleGeneralNoteBlur = useCallback(() => {
    const text = generalNoteText.trim();
    if (!text || !labResponse) return;
    saveGeneralNote(labResponse.lab_id, text, getStudentId()).catch(() => { });

    setLabResponse((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        lab: {
          ...prev.lab,
          general_notes: [...(prev.lab.general_notes || []), { content: text }],
        },
      };
    });

    setGeneralNoteSaved(true);
    setTimeout(() => setGeneralNoteSaved(false), 2000);
    setGeneralNoteText('');
  }, [generalNoteText, labResponse]);

  function handleAskQuestion(cell: LabCell, question: SuggestedQuestion, cellIndex: number) {
    if (askedQuestions.has(question.question)) return;
    setAskedQuestions((prev) => new Set([...prev, question.question]));
    if (labResponse) {
      markQuestionAsked(labResponse.lab_id, cell.id, question.question, getStudentId()).catch(() => { });
    }
    // Prefill bubble with the question and trigger narration
    setBubbleText(`You asked: "${question.question}" — Let me explain...`);
    explainCell(cellIndex, 'explain', true);
  }

  // ────────────────────────────────────────────────────────────

  function continueToProblemSet() {
    // Fire lab completion + profiler as background (no await)
    if (labResponse) {
      completeLab({
        labId: labResponse.lab_id,
        studentId: getStudentId(),
        courseId: resolvedCourseId,
        sessionNumber: resolvedSessionId,
      }).catch(() => { });
    }

    // Pass slides and lab cells so the problem set has full context
    const labCells = lab?.cells?.map(c => ({
      id: c.id,
      cell_type: c.cell_type,
      title: c.title,
      narrative: c.narrative || '',
      code: c.code || '',
      starter_code: c.starter_code || '',
      task_prompt: c.task_prompt || '',
    })) || [];

    navigate(`/course/${resolvedCourseId}/session/${resolvedSessionId}/problem-set`, {
      state: {
        nextSessionId: state.nextLessonId ?? null,
        courseId: resolvedCourseId,
        sessionTitle: state.lessonTitle || lab?.title || 'this session',
        sessionId: state.sessionId,
        studentProfileSummary: state.studentProfileSummary || '',
        slides: state.slides || [],
        labCells,
      },
    });
  }

  if (loading) {
    return (
      <TypewriterLoader
        variant="fixed"
        label="PREPARING YOUR CODING LAB"
        caption="Building a hands-on notebook for this session"
        messages={LOADING_STEPS}
      />
    );
  }

  if (error || !labResponse || !lab) {
    return (
      <div className="codex coding-lab-page">
        <style>{LAB_STYLES}</style>
        <div className="lab-error">
          <div className="lab-error-panel">
            <h1>Lab generation failed</h1>
            <p>{error || 'Could not load the coding lab.'}</p>
            <button onClick={() => loadLab(true)}>
              <RefreshCw size={16} />
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }

  const current = lab.cells[activeCell];
  const bubbleStyle: CSSProperties = {
    ...bubblePosition,
    opacity: isInitialPositioned ? 1 : 0,
    transition: isInitialPositioned ? undefined : 'none',
    visibility: isInitialPositioned ? 'visible' : 'hidden'
  };
  const displayedBubbleText = bubbleText || current?.tutor_script || lab.tutor_opening;

  return (
    <div className="codex coding-lab-page">
      <style>{LAB_STYLES}</style>
      <audio
        ref={audioRef}
        onEnded={() => { setIsNarrating(false); setIsPaused(false); isPausedRef.current = false; }}
        onTimeUpdate={() => {
          const audio = audioRef.current;
          if (audio && isNarrating && audio.duration) {
            if (!hasSwappedRef.current && audio.currentTime > audio.duration / 2) {
              setNarrationSide(prev => prev === 'right' ? 'left' : 'right');
              hasSwappedRef.current = true;
            }
          }
        }}
        style={{ display: 'none' }}
      />

      <header className="lab-header">
        <button className="lab-icon-button" onClick={() => navigate(`/course/${resolvedCourseId}/session/${resolvedSessionId}`)}>
          <ArrowLeft size={18} />
        </button>
        <div>
          <span className="lab-kicker">Notebook Lab</span>
          <h1>{lab.title}</h1>
        </div>
        <div className="lab-header-actions">
          <button className="lab-secondary-button" onClick={() => navigate(-1)}>
            <ArrowLeft size={15} />
            Back
          </button>
        </div>
      </header>

      <aside className={`lab-tutor-bubble ${isNarrating ? 'speaking' : ''}`} style={bubbleStyle}>
        <div className="lab-tutor-avatar">
          <Nova3DAvatar
            audioRef={audioRef}
            emotion={isNarrating ? 'excited' : 'happy'}
            blendshapeData={blendshapes}
            size={72}
            isFloating
          />
        </div>
        <div className="lab-tutor-body">
          <div className="lab-tutor-title">
            <Sparkles size={14} />
            LearnPal
          </div>
          <p>{displayedBubbleText}</p>
          <div className="lab-tutor-controls">
            <button onClick={handlePlayPause} disabled={!audioRef.current?.src || narratingCellId !== current?.id}>
              {isPaused ? <Play size={12} /> : <Pause size={12} />}
              {isPaused ? 'Resume' : 'Pause'}
            </button>
            <button onClick={() => explainCell(activeCell)} disabled={isNarrating}>
              {isNarrating && narratingCellId === current?.id ? <Loader2 size={12} className="lab-spin" /> : <Volume2 size={12} />}
              {isNarrating && narratingCellId === current?.id ? 'Speaking' : 'Explain'}
            </button>
            <button onClick={() => explainCell(activeCell + 1)} disabled={activeCell >= lab.cells.length - 1 || isNarrating}>
              Next cell
            </button>
          </div>
        </div>
      </aside>

      <main className={`lab-shell tutor-side-${narrationSide}`}>
        <section className="lab-main">
          <div className="lab-intro">
            <BookOpen size={18} />
            <p>{lab.intro}</p>
            <button className="lab-guide-button" onClick={() => explainCell(0)} disabled={isNarrating}>
              <Volume2 size={15} />
              Start Lab Walkthrough
            </button>
          </div>

          <div className="notebook">
            {lab.cells.map((cell, index) => {
              const active = index === activeCell;
              const done = completedTasks.has(cell.id);
              const visibleTips = (cell.tips || []).slice(0, tipIndex[cell.id] ?? 0);
              const hasQuestions = cell.suggested_questions && cell.suggested_questions.length > 0;

              return (
                <div key={cell.id} className={`cell-row ${narrationSide === 'right' ? 'tutor-right' : 'tutor-left'}`}>
                  <div
                    ref={(node) => { cellRefs.current[index] = node; }}
                    className={`notebook-cell ${active ? 'active' : ''} ${cell.cell_type}`}
                    onFocus={() => setActiveCell(index)}
                  >
                    <div className="cell-gutter">
                      <button onClick={() => goToCell(index)}>
                        {cell.cell_type === 'task' && done ? <CheckCircle2 size={16} /> : <Play size={14} />}
                      </button>
                      <span>[{index + 1}]</span>
                    </div>

                    <div className="cell-body">
                      <div className="cell-heading">
                        <span className="cell-type">{cell.cell_type}</span>
                        <h2>{cell.title}</h2>
                      </div>

                      {cell.narrative && <p className="cell-narrative">{cell.narrative}</p>}

                      {cell.cell_type === 'code' && cell.code && (
                        <>
                          <pre className="code-block"><code>{cell.code}</code></pre>
                          {cell.expected_output && (
                            <div className="cell-output">
                              <span>Output</span>
                              <pre>{cell.expected_output}</pre>
                            </div>
                          )}
                          <div className="task-actions code-actions">
                            <button onClick={() => runCell(cell)} disabled={runningCellId === cell.id}>
                              {runningCellId === cell.id ? <Loader2 size={15} className="lab-spin" /> : <Code2 size={15} />}
                              Run cell
                            </button>
                          </div>
                        </>
                      )}

                      {cell.cell_type === 'task' && (
                        <div className="task-cell">
                          <p className="task-prompt">{cell.task_prompt}</p>
                          <textarea
                            value={taskCode[cell.id] ?? codeFor(cell)}
                            onChange={(event) => setTaskCode((prev) => ({ ...prev, [cell.id]: event.target.value }))}
                            spellCheck={false}
                          />

                          {cell.success_criteria && cell.success_criteria.length > 0 && (
                            <div className="criteria">
                              <h3>Success criteria</h3>
                              {cell.success_criteria.map((criterion) => (
                                <div key={criterion} className="criterion">
                                  <CheckCircle2 size={13} />
                                  <span>{criterion}</span>
                                </div>
                              ))}
                            </div>
                          )}

                          {visibleTips.length > 0 && (
                            <div className="tips">
                              {visibleTips.map((tip, tipNumber) => (
                                <p key={`${cell.id}-${tip}`}>Tip {tipNumber + 1}: {tip}</p>
                              ))}
                            </div>
                          )}

                          <div className="task-actions">
                            <button onClick={() => showNextTip(cell, index)} disabled={(tipIndex[cell.id] ?? 0) >= (cell.tips?.length ?? 0)}>
                              <Lightbulb size={15} />
                              Say tip
                            </button>
                            <button onClick={() => runCell(cell)} disabled={runningCellId === cell.id}>
                              {runningCellId === cell.id ? <Loader2 size={15} className="lab-spin" /> : <Code2 size={15} />}
                              Run code
                            </button>
                            <button className="primary" onClick={() => markTaskDone(cell)} disabled={done}>
                              <CheckCircle2 size={15} />
                              {done ? 'Completed' : 'Mark complete'}
                            </button>
                          </div>
                        </div>
                      )}

                      {runResults[cell.id] && (
                        <div className={`lab-run-output ${runResults[cell.id].success ? 'success' : 'error'}`}>
                          <span>{runResults[cell.id].success ? 'Run output' : 'Run error'}</span>
                          <pre>{runResults[cell.id].stdout || runResults[cell.id].stderr || '(no output)'}</pre>
                        </div>
                      )}

                      {/* Cell notes */}
                      <div className="cell-notes">
                        <button
                          className={`cell-notes-toggle ${cellNoteOpen[cell.id] ? 'open' : ''}`}
                          onClick={() =>
                            setCellNoteOpen((prev) => ({ ...prev, [cell.id]: !prev[cell.id] }))
                          }
                        >
                          <StickyNote size={13} />
                          Notes
                          {(cell.student_notes?.length ?? 0) > 0 && (
                            <span style={{ marginLeft: 4, opacity: 0.7 }}>
                              ({cell.student_notes!.length})
                            </span>
                          )}
                          <ChevronDown size={13} />
                        </button>
                        {cellNoteOpen[cell.id] && (
                          <div className="cell-notes-body">
                            {cell.student_notes && cell.student_notes.length > 0 && (
                              <ul className="cell-notes-list">
                                {cell.student_notes.map((note, ni) => (
                                  <li key={ni}>{note.content}</li>
                                ))}
                              </ul>
                            )}
                            <textarea
                              placeholder="Add a note for this cell..."
                              value={cellNoteText[cell.id] || ''}
                              onChange={(e) =>
                                setCellNoteText((prev) => ({ ...prev, [cell.id]: e.target.value }))
                              }
                              onBlur={() => handleCellNoteBlur(cell.id)}
                            />
                            <div className={`cell-notes-saved ${cellNoteSaved[cell.id] ? 'visible' : ''}`}>
                              <Save size={11} /> Saved
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Suggested questions — separate box next to the cell */}
                  {hasQuestions && (
                    <div className="sq-box">
                      <div
                        className="sq-box-header"
                        style={{ cursor: 'pointer', userSelect: 'none' }}
                        onClick={() => setSqBoxOpen(prev => ({ ...prev, [cell.id]: !prev[cell.id] }))}
                      >
                        <HelpCircle size={14} />
                        <span>Relevant Questions</span>
                        <ChevronDown
                          size={14}
                          style={{
                            marginLeft: 'auto',
                            transform: sqBoxOpen[cell.id] ? 'rotate(180deg)' : 'none',
                            transition: 'transform 150ms'
                          }}
                        />
                      </div>
                      {sqBoxOpen[cell.id] && (
                        <div className="sq-box-list">
                          {cell.suggested_questions!.slice(0, 3).map((sq) => {
                            const isAsked = sq.was_asked || askedQuestions.has(sq.question);
                            return (
                              <button
                                key={sq.question}
                                className={`sq-chip ${isAsked ? 'asked' : ''}`}
                                onClick={() => !isAsked && handleAskQuestion(cell, sq, index)}
                                disabled={isAsked}
                              >
                                <HelpCircle size={12} />
                                {sq.question}
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="lab-finish-panel">
            <div>
              <h2>Ready for the problem set?</h2>
              <p>{allTasksDone ? lab.completion_message : 'Complete the lab tasks first to get ready for the problem set.'}</p>
            </div>
            <button onClick={finishLab} disabled={!allTasksDone}>
              Finish Lab
              <ChevronRight size={18} />
            </button>
          </div>
        </section>
      </main>

      {/* Global notepad widget container */}
      <div
        ref={fabRef}
        style={{
          position: 'fixed',
          left: fabPos.x !== -1 ? fabPos.x : undefined,
          top: fabPos.y !== -1 ? fabPos.y : undefined,
          right: fabPos.x !== -1 ? 'auto' : 24,
          bottom: fabPos.y !== -1 ? 'auto' : 24,
          zIndex: 50
        }}
      >
        {/* Notepad panel — floating above the FAB */}
        {notepadOpen && (
          <div
            className="notepad-panel"
            ref={notepadRef}
            style={{
              position: 'absolute',
              bottom: 'calc(100% + 16px)',
              right: 0,
              zIndex: 51,
            }}
          >
            <div
              className="notepad-header"
              style={{ cursor: 'grab' }}
              onMouseDown={(e) => {
                if (!fabRef.current) return;
                const rect = fabRef.current.getBoundingClientRect();
                dragMovedRef.current = false;
                dragFabRef.current = { dragging: true, offsetX: e.clientX - rect.left, offsetY: e.clientY - rect.top };
              }}
            >
              <StickyNote size={15} />
              <h3>Lab Notepad</h3>
              <button onClick={() => setNotepadOpen(false)} onMouseDown={(e) => e.stopPropagation()}>
                <X size={14} />
              </button>
            </div>
            <div className="notepad-body">
              {lab.general_notes && lab.general_notes.length > 0 && (
                <ul className="notepad-notes-list">
                  {lab.general_notes.map((note, ni) => (
                    <li key={ni}>{note.content}</li>
                  ))}
                </ul>
              )}
              <textarea
                placeholder="Write general notes about this lab..."
                value={generalNoteText}
                onChange={(e) => setGeneralNoteText(e.target.value)}
                onBlur={handleGeneralNoteBlur}
              />
              <div className={`notepad-saved ${generalNoteSaved ? 'visible' : ''}`}>
                <Save size={11} /> Saved
              </div>
            </div>
          </div>
        )}

        {/* Global notepad FAB */}
        <button
          className="notepad-fab"
          style={{ position: 'relative', right: 'auto', bottom: 'auto' }}
          onMouseDown={(e) => {
            if (!fabRef.current) return;
            const rect = fabRef.current.getBoundingClientRect();
            dragMovedRef.current = false; // reset drag flag
            dragFabRef.current = { dragging: true, offsetX: e.clientX - rect.left, offsetY: e.clientY - rect.top };
          }}
          onClick={(e) => {
            if (dragMovedRef.current) {
              dragMovedRef.current = false;
              return; // was dragging, don't open
            }
            setNotepadOpen((prev) => !prev);
          }}
        >
          <StickyNote size={22} />
          {(lab.general_notes?.length ?? 0) > 0 && (
            <span className="notepad-badge">{lab.general_notes!.length}</span>
          )}
        </button>
      </div>

      {showCompletion && (
        <div className="completion-overlay">
          <div className="completion-card">
            <div className="completion-ring">
              <CheckCircle2 size={64} />
            </div>
            <h2>Session Lab Complete</h2>
            <p>You practiced the concepts and syntax. Now tackle the problem set!</p>
            <button onClick={continueToProblemSet}>
              <Code2 size={18} />
              Continue to Problem Set
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

