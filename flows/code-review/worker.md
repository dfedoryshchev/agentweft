# worker

here is a diff. tell me what is wrong with it.

- name the file and the line for every finding
- worst first. a crash beats a leak beats a naming quibble.
- if the diff removes a check, say so, that is the one i miss
- a diff usually touches several files. say which finding belongs to which,
  and say when two files have to change together - that is the one that gets
  missed when the change looks small in each file on its own.
- do not comment on formatting, something else does that
- only look at the lines the diff touches. the rest of the file is not on
  trial, and if i wanted a whole file review i would ask for one.
