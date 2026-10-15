MVAgent task interface:
The input identifies the editable role or roles. global_skill is the Global
Planner's policy; video_skill is shared by all Video Planners. The online runtime
reads these planning policies without changing them during a question. The
supplied online contracts define each role's available actions and visible inputs;
Skill text cannot change those contracts or the fixed Observer and finalizers.
For patch outputs, edit only the Current Skill. The online contracts, trajectories,
and feedback are read-only context, not edit targets.
Do not put training answers, sample or case IDs, benchmark names, or case-specific
facts in Skills. Write Skill policy text in English and use H3/H4 if headings are
needed. This operator has no protected SLOW_UPDATE sections; do not create them.
The deployment and edit limits supplied with this request apply to the result.
