#ifndef VELA_SPINE_H
#define VELA_SPINE_H
#ifdef _WIN32
#define SP_API __declspec(dllexport)
#else
#define SP_API
#endif
#define SP_MAX_TAGS 8
#define SP_MAX_ROBOTS 4
/* Input levels 0..5; -1 means unknown. Policy threshold uses strict >. */
typedef struct { int consequence, urgency, exposure, spread, fresh; } sp_event;
typedef struct { int score, decision, unknown_mask; } sp_assessment;
enum { SP_AUTO = 0, SP_REVIEW = 1, SP_IMMEDIATE = 2 };
SP_API int sp_assess(const sp_event *event, int threshold, sp_assessment *out);
/* Conservative per-tag energy cost including reserve supplied by validated
 * route adapter. Cost matrix must not include unknown/unreachable edges.
 * Active ownership is excluded by caller until cancellation is confirmed. */
typedef struct {
  int tags, robots;
  int budget[SP_MAX_ROBOTS];
  int priority[SP_MAX_TAGS];
  int eligible[SP_MAX_TAGS * SP_MAX_ROBOTS];
  int energy[SP_MAX_TAGS * SP_MAX_ROBOTS];
  int cost[SP_MAX_TAGS * SP_MAX_ROBOTS];
} sp_problem;
typedef struct {
  int owner[SP_MAX_TAGS]; /* -1 unassigned; explicit, never silent */
  int uncovered_priority, total_cost;
} sp_allocation;
SP_API int sp_allocate(const sp_problem *problem, sp_allocation *out);
#endif
