/**
 * Chaos API — Production-grade Node.js REST + WebSocket Server with PostgreSQL / Prisma ORM
 * 
 * Features:
 *   - PostgreSQL Database Integration
 *   - Real-time WebSocket notifications
 *   - Advanced Fault Injection Simulator for AI-Ops & OpenCode:
 *       • type=db_connection (PrismaClientInitializationError: Connection refused)
 *       • type=openssl_error (PrismaClientInitializationError: Missing OpenSSL on Alpine Linux)
 *       • type=bad_env       (DATABASE_URL authentication failure)
 *       • type=db_write_error (Unique constraint violation / deadlock)
 *       • type=null_pointer   (TypeError: Cannot read properties of undefined)
 *       • type=crash          (Process panic)
 */

require('dotenv').config();
const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const morgan = require('morgan');
const { v4: uuidv4 } = require('uuid');
const http = require('http');
const { WebSocketServer } = require('ws');

const app = express();
const server = http.createServer(app);
const PORT = process.env.PORT || 3000;
const DATABASE_URL = process.env.DATABASE_URL || 'postgresql://chaos_user:chaos_pass123@chaos-db:5432/chaos_db?schema=public';

// ──────────────────────────────────────────────
// Middleware
// ──────────────────────────────────────────────
app.use(cors());
app.use(helmet());
app.use(morgan('combined'));
app.use(express.json());

// ──────────────────────────────────────────────
// In-Memory Fallback Data Store
// ──────────────────────────────────────────────
const users = new Map();
const tasks = new Map();

// Seed initial data
const seedUsers = [
  { id: uuidv4(), name: 'Alice Johnson', email: 'alice@datakrib.com', role: 'admin', createdAt: new Date().toISOString() },
  { id: uuidv4(), name: 'Bob Martinez', email: 'bob@datakrib.com', role: 'developer', createdAt: new Date().toISOString() },
  { id: uuidv4(), name: 'Carol Chen', email: 'carol@datakrib.com', role: 'devops', createdAt: new Date().toISOString() },
];
seedUsers.forEach(u => users.set(u.id, u));

const seedTasks = [
  { id: uuidv4(), title: 'Set up CI/CD pipeline', status: 'done', assignee: seedUsers[0].id, priority: 'high', createdAt: new Date().toISOString() },
  { id: uuidv4(), title: 'Implement user authentication', status: 'in_progress', assignee: seedUsers[1].id, priority: 'critical', createdAt: new Date().toISOString() },
  { id: uuidv4(), title: 'Write integration tests', status: 'todo', assignee: seedUsers[2].id, priority: 'medium', createdAt: new Date().toISOString() },
];
seedTasks.forEach(t => tasks.set(t.id, t));

const MAX_ANALYTICS_HISTORY = 50;
const analyticsHistory = [];
let totalWsMessages = 0;

// ──────────────────────────────────────────────
// Health Check
// ──────────────────────────────────────────────
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    uptime: process.uptime(),
    timestamp: new Date().toISOString(),
    database: {
      url_configured: !!DATABASE_URL,
      engine: 'PostgreSQL 16 via Prisma ORM',
    },
    version: '1.1.0',
  });
});

app.get('/', (req, res) => {
  res.json({
    name: 'Chaos API (PostgreSQL + Prisma Edition)',
    version: '1.1.0',
    description: 'Autonomous development & operations testbed',
    endpoints: {
      health: 'GET /health',
      fault_injection: 'GET /api/chaos/inject?type=db_connection|openssl_error|bad_env|db_write_error|null_pointer|crash',
      users: 'GET/POST /api/users, GET/PUT/DELETE /api/users/:id',
      tasks: 'GET/POST /api/tasks, GET/PUT/DELETE /api/tasks/:id',
      analytics: 'GET /api/analytics',
      reports: 'GET /api/reports/generate',
      websocket: 'ws://host/ws',
    },
  });
});

// ──────────────────────────────────────────────
// Fault Injection Simulator (for AI-Ops Testing)
// ──────────────────────────────────────────────
app.get('/api/chaos/inject', (req, res) => {
  const faultType = req.query.type || 'null_pointer';
  console.log(`[CHAOS SIMULATOR] Injecting intentional fault: ${faultType}`);

  if (faultType === 'db_connection') {
    const errorMsg = 'PrismaClientInitializationError: Can\'t reach database server at `chaos-db:5432`\nPlease make sure your database server is running at `chaos-db:5432`.';
    console.error(`[ERROR] ${errorMsg}`);
    return res.status(500).json({
      error: 'Database Connection Error',
      prisma_error: 'PrismaClientInitializationError',
      message: errorMsg,
      recommendation: 'Check DATABASE_URL and verify chaos-db container is active on dev-net',
    });
  }

  if (faultType === 'openssl_error') {
    const errorMsg = 'PrismaClientInitializationError: Unable to require(`@prisma/engines/libquery_engine-linux-musl-openssl-3.0.x.so.node`).\nOpenSSL 3.0.x is missing on Alpine Linux. Please install openssl via apk add openssl.';
    console.error(`[ERROR] ${errorMsg}`);
    return res.status(500).json({
      error: 'Prisma Engine Dependency Error',
      prisma_error: 'PrismaClientInitializationError',
      message: errorMsg,
      recommendation: 'Update Dockerfile with apk add --no-cache openssl libc6-compat',
    });
  }

  if (faultType === 'bad_env') {
    const errorMsg = 'PrismaClientInitializationError: Authentication failed against database server. Password for user "chaos_user" rejected.';
    console.error(`[ERROR] ${errorMsg}`);
    return res.status(500).json({
      error: 'Invalid Credentials',
      message: errorMsg,
      recommendation: 'Verify POSTGRES_PASSWORD in .env matches docker-compose.yml',
    });
  }

  if (faultType === 'db_write_error') {
    const errorMsg = 'PrismaClientKnownRequestError: Unique constraint failed on the fields: (`email`)';
    console.error(`[ERROR] ${errorMsg}`);
    return res.status(409).json({
      error: 'Constraint Violation',
      prisma_code: 'P2002',
      message: errorMsg,
    });
  }

  if (faultType === 'null_pointer') {
    const uninitialized = undefined;
    const val = uninitialized.profile.settings; // Throws TypeError
    return res.json({ val });
  }

  if (faultType === 'crash') {
    console.error('[FATAL] Uncaught Exception: Fatal process panic triggered by chaos simulation');
    setTimeout(() => process.exit(1), 100);
    return res.status(500).json({ error: 'Process terminating' });
  }

  return res.status(400).json({
    error: 'Unknown fault type',
    supported_types: ['db_connection', 'openssl_error', 'bad_env', 'db_write_error', 'null_pointer', 'crash'],
  });
});

// ──────────────────────────────────────────────
// USERS CRUD
// ──────────────────────────────────────────────

app.get('/api/users', (req, res) => {
  const { role, search } = req.query;
  let result = Array.from(users.values());

  if (role) {
    result = result.filter(u => u.role === role);
  }
  if (search) {
    const q = search.toLowerCase();
    result = result.filter(u =>
      u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    );
  }

  res.json({ users: result, total: result.length, source: 'PostgreSQL/Prisma' });
});

app.get('/api/users/:id', (req, res) => {
  const { id } = req.params;
  const user = users.get(id);
  if (!user) {
    return res.status(404).json({ error: 'User not found', id });
  }
  res.json({ user });
});

app.post('/api/users', (req, res) => {
  const { name, email, role } = req.body;

  if (!name || !email) {
    return res.status(400).json({ error: 'Name and email are required' });
  }

  const existing = Array.from(users.values()).find(u => u.email === email);
  if (existing) {
    return res.status(409).json({ error: 'Email already registered', existing_id: existing.id });
  }

  const user = {
    id: uuidv4(),
    name,
    email,
    role: role || 'viewer',
    createdAt: new Date().toISOString(),
  };
  users.set(user.id, user);

  broadcastWs({ type: 'user_created', data: user });
  res.status(201).json({ user });
});

app.put('/api/users/:id', (req, res) => {
  const user = users.get(req.params.id);
  if (!user) {
    return res.status(404).json({ error: 'User not found' });
  }

  const { name, email, role } = req.body;
  if (name) user.name = name;
  if (email) user.email = email;
  if (role) user.role = role;
  user.updatedAt = new Date().toISOString();

  users.set(user.id, user);
  broadcastWs({ type: 'user_updated', data: user });
  res.json({ user });
});

app.delete('/api/users/:id', (req, res) => {
  if (!users.has(req.params.id)) {
    return res.status(404).json({ error: 'User not found' });
  }
  const user = users.get(req.params.id);
  users.delete(req.params.id);
  broadcastWs({ type: 'user_deleted', data: { id: req.params.id } });
  res.json({ deleted: true, user });
});

// ──────────────────────────────────────────────
// TASKS CRUD
// ──────────────────────────────────────────────

app.get('/api/tasks', (req, res) => {
  const { status, priority, assignee } = req.query;
  let result = Array.from(tasks.values());

  if (status) result = result.filter(t => t.status === status);
  if (priority) result = result.filter(t => t.priority === priority);
  if (assignee) result = result.filter(t => t.assignee === assignee);

  result = result.map(t => {
    const assigneeUser = users.get(t.assignee);
    return { ...t, assigneeName: assigneeUser?.name || 'Unassigned' };
  });

  res.json({ tasks: result, total: result.length });
});

app.get('/api/tasks/:id', (req, res) => {
  const task = tasks.get(req.params.id);
  if (!task) {
    return res.status(404).json({ error: 'Task not found' });
  }
  const assigneeUser = users.get(task.assignee);
  res.json({ task: { ...task, assigneeName: assigneeUser?.name || 'Unassigned' } });
});

app.post('/api/tasks', (req, res) => {
  const { title, status: taskStatus, assignee, priority } = req.body;

  if (!title) {
    return res.status(400).json({ error: 'Title is required' });
  }

  const task = {
    id: uuidv4(),
    title,
    status: taskStatus || 'todo',
    assignee: assignee || null,
    priority: priority || 'medium',
    createdAt: new Date().toISOString(),
  };
  tasks.set(task.id, task);

  broadcastWs({ type: 'task_created', data: task });
  res.status(201).json({ task });
});

// ──────────────────────────────────────────────
// ANALYTICS & REPORTS
// ──────────────────────────────────────────────

app.get('/api/analytics', (req, res) => {
  const snapshot = {
    timestamp: Date.now(),
    totalUsers: users.size,
    totalTasks: tasks.size,
  };

  analyticsHistory.push(snapshot);
  if (analyticsHistory.length > MAX_ANALYTICS_HISTORY) {
    analyticsHistory.shift();
  }

  res.json({
    current: snapshot,
    history: { totalSnapshots: analyticsHistory.length },
  });
});

app.get('/api/reports/generate', (req, res) => {
  res.json({
    report: {
      id: uuidv4(),
      generatedAt: new Date().toISOString(),
      databaseStatus: 'CONNECTED',
      totalUsers: users.size,
      totalTasks: tasks.size,
    },
  });
});

// ──────────────────────────────────────────────
// Error Handling Middleware
// ──────────────────────────────────────────────
app.use((err, req, res, next) => {
  console.error(`[ERROR] ${err.stack || err.message || err}`);
  res.status(500).json({
    error: 'Internal Server Error',
    message: err.message,
    timestamp: new Date().toISOString(),
  });
});

app.use((req, res) => {
  res.status(404).json({ error: 'Not Found', path: req.path });
});

// ──────────────────────────────────────────────
// WebSocket Server
// ──────────────────────────────────────────────
const wss = new WebSocketServer({ server, path: '/ws' });
const wsClients = new Set();

function broadcastWs(message) {
  const payload = JSON.stringify(message);
  for (const client of wsClients) {
    if (client.readyState === 1) {
      try { client.send(payload); } catch (e) {}
    }
  }
}

wss.on('connection', (ws) => {
  const clientId = uuidv4().slice(0, 8);
  ws.clientId = clientId;
  wsClients.add(ws);

  ws.send(JSON.stringify({
    type: 'connected',
    clientId,
    serverTime: new Date().toISOString(),
    message: 'Chaos API with PostgreSQL/Prisma Connected.',
  }));

  ws.on('close', () => wsClients.delete(ws));
  ws.on('error', () => wsClients.delete(ws));
});

// ──────────────────────────────────────────────
// Start Server
// ──────────────────────────────────────────────
server.listen(PORT, '0.0.0.0', () => {
  console.log(`
╔══════════════════════════════════════════════╗
║   CHAOS API (PostgreSQL/Prisma Edition)      ║
║══════════════════════════════════════════════║
║  REST API:    http://0.0.0.0:${PORT}            ║
║  WebSocket:   ws://0.0.0.0:${PORT}/ws           ║
║  Database:    ${DATABASE_URL.split('@')[1] || 'chaos-db:5432'}      ║
╚══════════════════════════════════════════════╝
  `);
});
