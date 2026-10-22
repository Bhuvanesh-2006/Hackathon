import AddCommentOutlinedIcon from '@mui/icons-material/AddCommentOutlined';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import SendRoundedIcon from '@mui/icons-material/SendRounded';
import {
  Alert, Avatar, Box, Button, Card, Chip, CircularProgress, IconButton, MenuItem, Stack, TextField, Tooltip, Typography,
} from '@mui/material';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AnswerCard } from '../components/AnswerCard';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { ContextBar } from '../components/ContextBar';
import { SaveQueryDialog, type SaveDraft } from '../components/SaveQueryDialog';
import { useDatasets } from '../hooks/DatasetContext';
import { useToast } from '../components/Toast';
import { api, ApiError } from '../services/api';
import { tokens } from '../theme/theme';
import type { AgentResponse, ConversationContext } from '../types/api';

const EXAMPLES = [
  'Which products generated the highest revenue?',
  'Which products had the most returned units?',
  'Which countries generated the highest revenue?',
  'What were the monthly revenue trends?',
  'Which customers contributed the most revenue?',
  'How much revenue was associated with cancelled invoices?',
  'Who are our best customers?',
];

interface Message {
  id: string;
  role: 'user' | 'agent';
  text?: string;
  response?: AgentResponse;
  pending?: boolean;
  failure?: string;
  request?: Payload;
}

interface Payload {
  question: string;
  conversation_id?: string | null;
  clarification_response?: string | null;
  rerun?: boolean;
}

let seq = 0;
const nextId = () => `m${++seq}`;

export default function AnalystPage() {
  const [params, setParams] = useSearchParams();
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [context, setContext] = useState<ConversationContext | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const notify = useToast();
  const { datasets, activeId, setActive } = useDatasets();
  const [convDataset, setConvDataset] = useState<string | null>(null);
  const datasetId = convDataset ?? activeId;
  const datasetRef = useRef<string | null>(datasetId);
  datasetRef.current = datasetId;
  const [pendingDataset, setPendingDataset] = useState<string | null>(null);
  const [saveDraft, setSaveDraft] = useState<SaveDraft | null>(null);
  const readyDatasets = datasets.filter((d) => d.status === 'ready');
  const currentDataset = datasets.find((d) => d.id === datasetId);

  const lastAgent = [...messages].reverse().find((m) => m.role === 'agent' && m.response);
  const awaitingClarification = lastAgent?.response?.status === 'clarification';

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  // Reopen a query from history: /analyst?query=<id>
  useEffect(() => {
    const qid = params.get('query');
    if (!qid) return;
    api.historyItem(qid)
      .then((r) => {
        setConversationId(r.conversation_id);
        setContext(r.context ?? null);
        setConvDataset(r.dataset?.id ?? 'online_retail_ii');
        setMessages([
          { id: nextId(), role: 'user', text: r.question + (r.clarification_response ? ` → ${r.clarification_response}` : '') },
          { id: nextId(), role: 'agent', response: r },
        ]);
      })
      .catch((e: Error) => notify(e.message, 'error'))
      .finally(() => setParams({}, { replace: true }));
  }, [params, setParams, notify]);

  // Prefill a question (e.g. adapting a saved query to the selected dataset): /analyst?ask=<text>
  useEffect(() => {
    const q = params.get('ask');
    if (!q) return;
    setInput(q.slice(0, 500));
    setParams({}, { replace: true });
  }, [params, setParams]);

  // Continue an investigation seeded from an anomaly: /analyst?conversation=<id>
  useEffect(() => {
    const cid = params.get('conversation');
    if (!cid) return;
    api.conversation(cid)
      .then((r) => {
        setConversationId(r.conversation_id);
        setContext(r.context);
        setConvDataset('online_retail_ii');
        setMessages([]);
      })
      .catch((e: Error) => notify(e.message, 'error'))
      .finally(() => setParams({}, { replace: true }));
  }, [params, setParams, notify]);

  const send = useCallback(async (payload: Payload, userText: string) => {
    const pendingId = nextId();
    setMessages((m) => [...m, { id: nextId(), role: 'user', text: userText }, { id: pendingId, role: 'agent', pending: true, request: payload }]);
    setBusy(true);
    try {
      const r = await api.ask({ ...payload, dataset_id: datasetRef.current });
      if (r.dataset) setConvDataset(r.dataset.id);
      setConversationId(r.conversation_id);
      if (r.context) setContext(r.context);
      setMessages((m) => m.map((x) => (x.id === pendingId ? { ...x, pending: false, response: r } : x)));
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : 'Unexpected error';
      setMessages((m) => m.map((x) => (x.id === pendingId ? { ...x, pending: false, failure: msg } : x)));
    } finally {
      setBusy(false);
    }
  }, []);

  const ask = (text?: string) => {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput('');
    if (awaitingClarification && !text) {
      send({ question: '', conversation_id: conversationId, clarification_response: q }, q);
    } else {
      send({ question: q, conversation_id: conversationId }, q);
    }
  };

  const clarify = (option: string) => send({ question: '', conversation_id: conversationId, clarification_response: option }, option);

  const retry = (payload: Payload | undefined, response?: AgentResponse) => {
    const p = payload ?? (response ? { question: response.question, conversation_id: conversationId, clarification_response: response.clarification_response } : null);
    if (!p) return;
    send(p, p.clarification_response ?? p.question);
  };

  const newConversation = () => {
    setConvDataset(null);
    setMessages([]);
    setConversationId(null);
    setContext(null);
    setInput('');
  };

  const canRerun = Boolean(context?.root_question);
  const updateContext = async (body: { remove?: string[]; clear_filters?: boolean; clear_comparison?: boolean }, rerunLabel: string) => {
    if (!conversationId) return;
    try {
      const r = await api.patchConversation(conversationId, body);
      setContext(r.context);
      if (canRerun) send({ question: '', conversation_id: conversationId, rerun: true }, rerunLabel);
      else notify('Context updated; it applies to your next question', 'info');
    } catch (e) {
      notify((e as Error).message, 'error');
    }
  };

  const applyDataset = async (id: string) => {
    newConversation();
    try {
      await setActive(id);
      notify(`Now querying “${datasets.find((d) => d.id === id)?.name ?? id}”`, 'info');
    } catch (e) {
      notify((e as Error).message, 'error');
    }
  };
  const chooseDataset = (id: string) => {
    if (id === datasetId) return;
    if (messages.length > 0 || conversationId) setPendingDataset(id);
    else void applyDataset(id);
  };
  const openSave = (r: AgentResponse) => {
    const dsId = r.dataset?.id ?? datasetId ?? 'online_retail_ii';
    setSaveDraft({
      title: r.question.slice(0, 120), question: r.question, sql: r.sql ?? '', description: r.explanation ?? '',
      category: 'General', tags: [], parameters: [], dataset_id: dsId,
      dataset_name: r.dataset?.name ?? datasets.find((d) => d.id === dsId)?.name ?? dsId,
    });
  };

  return (
    <Stack sx={{ minHeight: { xs: 'calc(100vh - 96px)', sm: 'calc(100vh - 112px)' } }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="h5">AI Sales Analyst</Typography>
          <TextField select size="small" label="Dataset" value={datasetId ?? ''} onChange={(e) => chooseDataset(e.target.value)}
            disabled={busy || readyDatasets.length === 0} sx={{ mt: 1, mb: 0.5, minWidth: { xs: '100%', sm: 320 } }}
            inputProps={{ 'aria-label': 'Dataset to query' }}>
            {readyDatasets.map((d) => (
              <MenuItem key={d.id} value={d.id}>{d.name}{d.kind === 'builtin' ? ' · demo' : ''} ({(d.row_count ?? 0).toLocaleString('en-GB')} rows)</MenuItem>
            ))}
          </TextField>
          <Typography variant="body2" color="text.secondary">Ask in plain English. Every answer shows the validated SQL it ran and the rules it applied.</Typography>
        </Box>
        <Tooltip title="Start a new conversation">
          <span>
            <Button variant="outlined" startIcon={<AddCommentOutlinedIcon />} onClick={newConversation} disabled={busy || (messages.length === 0 && !context)}
              sx={{ display: { xs: 'none', sm: 'inline-flex' } }}>New chat</Button>
            <IconButton aria-label="New conversation" onClick={newConversation} disabled={busy || (messages.length === 0 && !context)} sx={{ display: { xs: 'inline-flex', sm: 'none' } }}>
              <AddCommentOutlinedIcon />
            </IconButton>
          </span>
        </Tooltip>
      </Stack>

      <Stack spacing={2} sx={{ flex: 1, pb: 2 }}>
        {messages.length === 0 && context?.topic && (
          <Card sx={{ p: { xs: 2.5, sm: 3 } }}>
            <Stack spacing={1.5}>
              <Typography variant="overline" color="secondary.light">Investigating a potential anomaly</Typography>
              <Typography variant="h6">{context.topic.summary}</Typography>
              <Typography variant="body2" color="text.secondary">
                Questions in this conversation are limited to that week (see the date chip below). Remove the chip to widen the scope.
                Breakdowns describe where a change is concentrated; they do not prove its cause.
              </Typography>
              <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1}>
                {['Which products generated the most revenue?', 'Which countries generated the highest revenue?',
                  'Which products had the most returned units?', 'Compare with the previous period'].map((q) => (
                  <Chip key={q} label={q} onClick={() => ask(q)} clickable variant="outlined" color="primary"
                    sx={{ height: 'auto', py: 0.75, '& .MuiChip-label': { whiteSpace: 'normal' } }} />
                ))}
              </Stack>
            </Stack>
          </Card>
        )}

        {messages.length === 0 && !context?.topic && (
          <Card sx={{ p: { xs: 2.5, sm: 4 } }}>
            <Stack spacing={2} alignItems="flex-start">
              <Avatar sx={{ bgcolor: tokens.primary, width: 48, height: 48 }}><AutoAwesomeIcon /></Avatar>
              <Typography variant="h6">What would you like to know about your sales?</Typography>
              <Typography variant="body2" color="text.secondary">
                Revenue means <b>net revenue</b> (sales minus cancellations, product lines only) unless you say otherwise. Money is in GBP.
                Ambiguous questions get a clarifying question instead of a guess.
              </Typography>
              <Stack direction="row" flexWrap="wrap" useFlexGap spacing={1}>
                {EXAMPLES.map((q) => (
                  <Chip key={q} label={q} onClick={() => ask(q)} clickable variant="outlined" color="primary"
                    sx={{ height: 'auto', py: 0.75, '& .MuiChip-label': { whiteSpace: 'normal' } }} />
                ))}
              </Stack>
            </Stack>
          </Card>
        )}

        {messages.map((m) =>
          m.role === 'user' ? (
            <Box key={m.id} sx={{ alignSelf: 'flex-end', maxWidth: { xs: '92%', md: '70%' } }}>
              <Box sx={{ bgcolor: tokens.primary, color: '#fff', px: 2, py: 1.25, borderRadius: '18px 18px 4px 18px' }}>
                <Typography variant="body2" sx={{ fontWeight: 500, wordBreak: 'break-word' }}>{m.text}</Typography>
              </Box>
            </Box>
          ) : (
            <Stack key={m.id} direction="row" spacing={1.5} alignItems="flex-start" sx={{ width: '100%' }}>
              <Avatar sx={{ bgcolor: '#1a1f37', color: tokens.primary, width: 36, height: 36, display: { xs: 'none', sm: 'flex' } }}>
                <AutoAwesomeIcon fontSize="small" />
              </Avatar>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                {m.pending && (
                  <Card sx={{ p: 2 }}>
                    <Stack direction="row" spacing={1.5} alignItems="center">
                      <CircularProgress size={18} />
                      <Typography variant="body2" color="text.secondary">Planning query, validating SQL and running it on the dataset…</Typography>
                    </Stack>
                  </Card>
                )}
                {m.failure && (
                  <Alert severity="error" action={<Button color="inherit" size="small" onClick={() => retry(m.request)}>Retry</Button>}>
                    {m.failure}
                  </Alert>
                )}
                {m.response && (
                  <AnswerCard response={m.response} onClarify={clarify} clarifyDisabled={busy || m !== lastAgent} onSave={openSave}
                    onRetry={() => retry(m.request, m.response)} />
                )}
              </Box>
            </Stack>
          ),
        )}
        <div ref={bottomRef} />
      </Stack>

      <Box sx={{
        position: 'sticky', bottom: 0, pt: 1, pb: { xs: 1.5, sm: 2 }, bgcolor: tokens.bg, zIndex: 2,
        '&::before': { content: '""', position: 'absolute', left: 0, right: 0, top: -24, height: 24, pointerEvents: 'none',
          background: `linear-gradient(180deg, transparent, ${tokens.bg})` },
      }}>
        {context && (
          <ContextBar context={context} disabled={busy}
            onRemove={(field, label) => updateContext({ remove: [field] }, `Re-run without “${label}”`)}
            onClearComparison={() => updateContext({ clear_comparison: true }, 'Re-run without the comparison')}
            onClearAll={() => updateContext({ clear_filters: true }, 'Re-run without filters')} />
        )}
        <Card sx={{ p: 1 }}>
          <Stack direction="row" spacing={1} alignItems="flex-end">
            <TextField
              fullWidth multiline maxRows={4} value={input}
              onChange={(e) => setInput(e.target.value.slice(0, 500))}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  ask();
                }
              }}
              placeholder={awaitingClarification ? 'Pick an option above or type your own answer…' : `Ask about ${currentDataset ? currentDataset.name : 'your data'}…`}
              variant="standard"
              InputProps={{ disableUnderline: true, sx: { px: 1.5, py: 1, fontSize: 15 } }}
              inputProps={{ 'aria-label': 'Question' }}
            />
            <IconButton aria-label="Send question" color="primary" onClick={() => ask()} disabled={busy || !input.trim()}
              sx={{ bgcolor: tokens.primary, color: '#fff', width: 44, height: 44, '&:hover': { bgcolor: '#0062d6' }, '&.Mui-disabled': { bgcolor: 'rgba(0,117,255,0.25)' } }}>
              {busy ? <CircularProgress size={20} color="inherit" /> : <SendRoundedIcon />}
            </IconButton>
          </Stack>
        </Card>
        {messages.length > 0 && conversationId && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75, px: 1 }}>
            Follow-ups use this conversation's context, e.g. “now only for Germany”.
          </Typography>
        )}
      </Box>
      <ConfirmDialog open={pendingDataset !== null} title="Switch dataset?"
        body={<>Switching to <b>{datasets.find((d) => d.id === pendingDataset)?.name}</b> starts a new conversation. The current
          conversation stays in Query History. Results from different datasets are never mixed.</>}
        confirmLabel="Switch and start new chat" onClose={() => setPendingDataset(null)}
        onConfirm={() => { const id = pendingDataset; setPendingDataset(null); if (id) void applyDataset(id); }} />
      <SaveQueryDialog open={saveDraft !== null} draft={saveDraft} onClose={() => setSaveDraft(null)} onSaved={() => undefined} />
    </Stack>
  );
}
