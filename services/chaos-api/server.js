/**
 * Chaos API — Production-grade Node.js REST + WebSocket Server
 * 
 * Features:
 *   - Full CRUD for Users and Tasks
 *   - Real-time WebSocket notifications & chat
 *   - Analytics aggregation endpoint
 *   - Report generation endpoint
 *   - Health check endpoint
 *   - Proper middleware (CORS, Helmet, Morgan logging)
 *
 * ┌──────────────────────────────────────────────────────────────┐
 * │  INTENTIONAL BUGS PLANTED FOR AI-OPS STRESS TEST            │
 * │                                                              │
 * │  Bug #1 — Memory Leak                                       │
 * │    GET /api/analytics accumulates data in a global array     │
 * │    that is never cleared. After ~200 requests the process    │
 * │    memory balloons and eventually OOMs.                      │
 * │                                                              │
 * │  Bug #2 — Null Reference Crash                               │
 * │    GET /api/users/999 tries to read .toUpperCase() on        │
 * │    undefined, causing an uncaught TypeError that crashes     │
 * │    the process.                                              │
 * │                                                              │
 * │  Bug #3 — Intermittent 500 on Task Creation                  │
 * │    POST /api/tasks randomly throws a TypeError ~30% of      │
 * │    the time, simulating a flaky DB serialization bug.        │
 * │                                                              │
 * │  Bug #4 — WebSocket Crash                                    │
 * │    After 50 total WebSocket messages received across all     │
 * │    clients, the WS handler throws an unhandled error that    │
 * │    crashes the server.                                       │
 * │                                                              │
 * │  Bug #5 — Hanging Response                                   │
 * │    GET /api/reports/generate never sends a response,         │
 * │    causing the client to hang and leaking the connection.    │
 * └──────────────────────────────────────────────────────────────┘
 */

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

// ──────────────────────────────────────────────
// Middleware
// ──────────────────────────────────────────────
app.use(cors());
app.use(helmet());
app.use(morgan('combined'));
app.use(express.json());

// ──────────────────────────────────────────────
// In-Memory Data Store
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

// ──────────────────────────────────────────────
// BUG #1: Memory Leak — analytics accumulator
// This array grows on every /api/analytics call
// and is never garbage collected.
// ──────────────────────────────────────────────
const analyticsAccumulator = [];

// ──────────────────────────────────────────────
// BUG #4: WebSocket message counter for crash
// ──────────────────────────────────────────────
let totalWsMessages = 0;
const WS_CRASH_THRESHOLD = 50;

// ──────────────────────────────────────────────
// Health Check
// ──────────────────────────────────────────────
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    uptime: process.uptime(),
    timestamp: new Date().toISOString(),
    memory: process.memoryUsage(),
    version: '1.0.0',
  });
});

app.get('/', (req, res) => {
  res.json({
    name: 'Chaos API',
    version: '1.0.0',
    description: 'Production-grade REST + WebSocket API for AI-Ops stress testing',
    endpoints: {
      health: 'GET /health',
      users: 'GET/POST /api/users, GET/PUT/DELETE /api/users/:id',
      tasks: 'GET/POST /api/tasks, GET/PUT/DELETE /api/tasks/:id',
      analytics: 'GET /api/analytics',
      reports: 'GET /api/reports/generate',
      websocket: 'ws://host/ws',
    },
  });
});

// ──────────────────────────────────────────────
// USERS CRUD
// ──────────────────────────────────────────────

// GET all users
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

  res.json({ users: result, total: result.length });
});

// GET single user
app.get('/api/users/:id', (req, res) => {
  const { id } = req.params;

  // ──────────────────────────────────────────
  // BUG #2: Null reference crash
  // When id is "999", we deliberately look up
  // a non-existent user and call .toUpperCase()
  // on the undefined .department field.
  // This crashes the entire process.
  // ──────────────────────────────────────────
  if (id === '999') {
    const ghost = users.get('nonexistent-id');
    const dept = ghost.department.toUpperCase(); // TypeError: Cannot read properties of undefined
    return res.json({ department: dept });
  }

  const user = users.get(id);
  if (!user) {
    return res.status(404).json({ error: 'User not found', id });
  }
  res.json({ user });
});

// POST create user
app.post('/api/users', (req, res) => {
  const { name, email, role } = req.body;

  if (!name || !email) {
    return res.status(400).json({ error: 'Name and email are required' });
  }

  // Check duplicate email
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

// PUT update user
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

// DELETE user
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

// GET all tasks
app.get('/api/tasks', (req, res) => {
  const { status, priority, assignee } = req.query;
  let result = Array.from(tasks.values());

  if (status) result = result.filter(t => t.status === status);
  if (priority) result = result.filter(t => t.priority === priority);
  if (assignee) result = result.filter(t => t.assignee === assignee);

  // Enrich with assignee name
  result = result.map(t => {
    const assigneeUser = users.get(t.assignee);
    return { ...t, assigneeName: assigneeUser?.name || 'Unassigned' };
  });

  res.json({ tasks: result, total: result.length });
});

// GET single task
app.get('/api/tasks/:id', (req, res) => {
  const task = tasks.get(req.params.id);
  if (!task) {
    return res.status(404).json({ error: 'Task not found' });
  }
  const assigneeUser = users.get(task.assignee);
  res.json({ task: { ...task, assigneeName: assigneeUser?.name || 'Unassigned' } });
});

// POST create task
app.post('/api/tasks', (req, res) => {
  const { title, status: taskStatus, assignee, priority } = req.body;

  if (!title) {
    return res.status(400).json({ error: 'Title is required' });
  }

  // ──────────────────────────────────────────
  // BUG #3: Intermittent 500 error
  // Simulates a flaky database serialization
  // bug that fails ~30% of the time.
  // ──────────────────────────────────────────
  if (Math.random() < 0.3) {
    const badData = undefined;
    const serialized = JSON.parse(badData.toString()); // TypeError: Cannot read properties of undefined
    return res.json({ task: serialized });
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

// PUT update task
app.put('/api/tasks/:id', (req, res) => {
  const task = tasks.get(req.params.id);
  if (!task) {
    return res.status(404).json({ error: 'Task not found' });
  }

  const { title, status: taskStatus, assignee, priority } = req.body;
  if (title) task.title = title;
  if (taskStatus) task.status = taskStatus;
  if (assignee) task.assignee = assignee;
  if (priority) task.priority = priority;
  task.updatedAt = new Date().toISOString();

  tasks.set(task.id, task);
  broadcastWs({ type: 'task_updated', data: task });
  res.json({ task });
});

// DELETE task
app.delete('/api/tasks/:id', (req, res) => {
  if (!tasks.has(req.params.id)) {
    return res.status(404).json({ error: 'Task not found' });
  }
  const task = tasks.get(req.params.id);
  tasks.delete(req.params.id);
  broadcastWs({ type: 'task_deleted', data: { id: req.params.id } });
  res.json({ deleted: true, task });
});

// ──────────────────────────────────────────────
// ANALYTICS
// ──────────────────────────────────────────────

app.get('/api/analytics', (req, res) => {
  // ──────────────────────────────────────────
  // BUG #1: Memory Leak
  // Every call pushes a large object into a
  // global array that is never pruned.
  // After ~200 calls, memory usage will spike.
  // ──────────────────────────────────────────
  const snapshot = {
    timestamp: Date.now(),
    totalUsers: users.size,
    totalTasks: tasks.size,
    tasksByStatus: {},
    tasksByPriority: {},
    usersByRole: {},
    // Intentionally large payload to accelerate leak
    rawDump: Array.from(tasks.values()).map(t => ({ ...t, _pad: 'x'.repeat(10000) })),
  };

  // Count by status
  for (const t of tasks.values()) {
    snapshot.tasksByStatus[t.status] = (snapshot.tasksByStatus[t.status] || 0) + 1;
    snapshot.tasksByPriority[t.priority] = (snapshot.tasksByPriority[t.priority] || 0) + 1;
  }
  for (const u of users.values()) {
    snapshot.usersByRole[u.role] = (snapshot.usersByRole[u.role] || 0) + 1;
  }

  analyticsAccumulator.push(snapshot); // LEAK: never cleared

  res.json({
    current: {
      totalUsers: users.size,
      totalTasks: tasks.size,
      tasksByStatus: snapshot.tasksByStatus,
      tasksByPriority: snapshot.tasksByPriority,
      usersByRole: snapshot.usersByRole,
    },
    history: {
      totalSnapshots: analyticsAccumulator.length,
      memoryUsageMB: Math.round(process.memoryUsage().heapUsed / 1024 / 1024),
    },
  });
});

// ──────────────────────────────────────────────
// REPORTS
// ──────────────────────────────────────────────

app.get('/api/reports/generate', (req, res) => {
  // ──────────────────────────────────────────
  // BUG #5: Hanging Response
  // This endpoint never calls res.send() or
  // res.json(). The client connection hangs
  // indefinitely and the socket is leaked.
  // ──────────────────────────────────────────
  console.log('[REPORT] Generating report... (this will hang)');
  // Intentionally no response sent
});

// ──────────────────────────────────────────────
// Error Handling Middleware
// ──────────────────────────────────────────────
app.use((err, req, res, next) => {
  console.error(`[ERROR] ${err.stack}`);
  res.status(500).json({
    error: 'Internal Server Error',
    message: err.message,
    timestamp: new Date().toISOString(),
  });
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({
    error: 'Not Found',
    path: req.path,
    method: req.method,
  });
});

// ──────────────────────────────────────────────
// WebSocket Server
// ──────────────────────────────────────────────
const wss = new WebSocketServer({ server, path: '/ws' });
const wsClients = new Set();

function broadcastWs(message) {
  const payload = JSON.stringify(message);
  for (const client of wsClients) {
    if (client.readyState === 1) { // WebSocket.OPEN
      client.send(payload);
    }
  }
}

wss.on('connection', (ws, req) => {
  const clientId = uuidv4().slice(0, 8);
  ws.clientId = clientId;
  wsClients.add(ws);

  console.log(`[WS] Client ${clientId} connected (total: ${wsClients.size})`);

  // Send welcome message
  ws.send(JSON.stringify({
    type: 'connected',
    clientId,
    serverTime: new Date().toISOString(),
    message: 'Welcome to Chaos API WebSocket. Send JSON messages to interact.',
  }));

  // Broadcast join
  broadcastWs({
    type: 'client_joined',
    clientId,
    totalClients: wsClients.size,
  });

  ws.on('message', (data) => {
    totalWsMessages++;

    // ──────────────────────────────────────
    // BUG #4: WebSocket crash after threshold
    // After 50 total messages, this throws an
    // unhandled error that crashes the server.
    // ──────────────────────────────────────
    if (totalWsMessages >= WS_CRASH_THRESHOLD) {
      console.log(`[WS] CRASH TRIGGER: ${totalWsMessages} messages reached threshold`);
      const nullRef = null;
      nullRef.send('crash'); // TypeError: Cannot read properties of null
    }

    try {
      const msg = JSON.parse(data.toString());

      // Handle different message types
      switch (msg.type) {
        case 'chat':
          broadcastWs({
            type: 'chat',
            from: clientId,
            message: msg.message,
            timestamp: new Date().toISOString(),
          });
          break;

        case 'ping':
          ws.send(JSON.stringify({
            type: 'pong',
            timestamp: new Date().toISOString(),
            totalMessages: totalWsMessages,
          }));
          break;

        case 'subscribe':
          ws.send(JSON.stringify({
            type: 'subscribed',
            channel: msg.channel || 'default',
            timestamp: new Date().toISOString(),
          }));
          break;

        default:
          ws.send(JSON.stringify({
            type: 'echo',
            received: msg,
            totalMessages: totalWsMessages,
          }));
      }
    } catch (parseErr) {
      ws.send(JSON.stringify({
        type: 'error',
        message: 'Invalid JSON payload',
      }));
    }
  });

  ws.on('close', () => {
    wsClients.delete(ws);
    console.log(`[WS] Client ${clientId} disconnected (total: ${wsClients.size})`);
    broadcastWs({
      type: 'client_left',
      clientId,
      totalClients: wsClients.size,
    });
  });

  ws.on('error', (err) => {
    console.error(`[WS] Client ${clientId} error:`, err.message);
    wsClients.delete(ws);
  });
});

// ──────────────────────────────────────────────
// Start Server
// ──────────────────────────────────────────────
server.listen(PORT, '0.0.0.0', () => {
  console.log(`
╔══════════════════════════════════════════════╗
║         CHAOS API v1.0.0 — ONLINE           ║
║══════════════════════════════════════════════║
║  REST API:    http://0.0.0.0:${PORT}            ║
║  WebSocket:   ws://0.0.0.0:${PORT}/ws           ║
║  Health:      http://0.0.0.0:${PORT}/health     ║
║                                              ║
║  Users:       ${users.size} seeded                      ║
║  Tasks:       ${tasks.size} seeded                      ║
╚══════════════════════════════════════════════╝
  `);
});
