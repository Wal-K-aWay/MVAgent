The instruction being revised is a pair of separately deployed role
policies. Return the new instruction inside one fenced JSON object with exactly
these two string fields: global_skill and video_skill. Each policy may use only
its own role's runtime-visible inputs. You may make one coordinated change per
role. Copy the current text exactly for an unchanged role, including an empty
string when that role is currently empty. The program converts changed role
texts into bounded edits and evaluates the complete pair before accepting it.
