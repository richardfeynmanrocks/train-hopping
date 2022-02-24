//! A generic ant-colony simulation travelling salesman solver.

use std::collections::HashMap;

#[derive(Debug, Default, Clone)]
pub struct Colony {
    // Edge pheromone levels
    edges: HashMap<EdgeKey, Edge>,

    // Whether to use pheromone map A or B.
    use_map_b: bool,

    // The best path ever found, in increasing quality.
    // A quality of "0" indicates that no path has ever been found.
    best_path: (f32, Vec<usize>),

    // A reused path buffer.
    path_buf: Vec<usize>,
}

pub trait Visitor {
    type TargetIter: Iterator<Item = (f32, usize)>;

    /// Resets the visitor's state, moves it to a random initial node, and returns that node.
    fn reset(&mut self) -> usize;

    /// Enumerates the visitor's target nodes at a given index. This index should be consistent with
    /// the index the visitor is currently logically standing at.
    fn targets(&self, index: usize) -> Self::TargetIter;

    /// Updates the visitor's state such that it moves to a given node. This index should be one of
    /// the indices enumerated by [targets].
    fn walk_to(&mut self, index: usize);
}

pub trait Evaluator {
    /// Computes the overall edge's quality based off its [Visitor]-reported quality and pheromone
    /// level.
    fn edge_quality(&self, quality: f32, pheromone: f32) -> f32;

    /// Transforms the cumulative ([Visitor] reported; not [edge_quality]) quality of a given path
    /// into a quantity of pheromones to be deposited.
    fn pheromones_deposited(&self, total_quality: f32) -> f32;
}

impl Colony {
    pub fn new() -> Self {
        Self::default()
    }

    /// Runs a simulation generation with `ant_count`.
    ///
    /// The [Visitor] provides a way to extract contextual information about which nodes a "traveller"
    /// can move to as well as their related quality.
    ///
    /// The [Evaluator] provides a way to convert quality and pheromone levels into a single
    /// `edge_quality` number specifying *deterministically* how good a given edge is as well as
    /// convert a given overall path quality into the quantity of pheromones deposited at each
    /// travelled edge.
    pub fn run<V: Visitor, E: Evaluator>(
        &mut self,
        ant_count: usize,
        visitor: &mut V,
        evaluator: &E,
    ) {
        // Copy previous map pheromone levels to current map
        for edge in &mut self.edges.values_mut() {
            edge.copy_pheromones(self.use_map_b);
        }

        // Simulate ants
        for _ in 0..ant_count {
            // Clear ant's path buffer.
            self.path_buf.clear();

            // Store ant state.
            let mut total_quality = 0.;
            let mut curr_index = visitor.reset();

            // Travel until we've reached a terminal point.
            loop {
                let choice = visitor
                    .targets(curr_index)
                    .map(|(quality, target_index)| {
                        let pheromone = self.edges[&EdgeKey::new(curr_index, target_index)]
                            .get_pheromone(self.use_map_b);

                        let visit_quality = evaluator.edge_quality(quality, pheromone);

                        (visit_quality, quality, target_index)
                    })
                    .max_by(|(visit_quality_a, _, _), (visit_quality_b, _, _)| {
                        visit_quality_a.partial_cmp(visit_quality_b).unwrap()
                    });

                if let Some((_, quality, target_index)) = choice {
                    // Accumulate the quality of the path.
                    total_quality += quality;

                    // Move to the target node.
                    curr_index = target_index;
                    visitor.walk_to(curr_index);
                    self.path_buf.push(curr_index);
                } else {
                    // We're at a dead end. Our job is done.
                    break;
                }
            }

            // Push the last node, completing the path.
            self.path_buf.push(curr_index);

            // Deposit pheromones
            let deposited = evaluator.pheromones_deposited(total_quality);
            for i in 0..(self.path_buf.len() - 1) {
                let key = EdgeKey::new(self.path_buf[i], self.path_buf[i + 1]);
                let curr_level = self
                    .edges
                    .get_mut(&key)
                    .unwrap()
                    .get_pheromone_mut(self.use_map_b);

                *curr_level += deposited;
            }

            // Update best path
            if total_quality > self.best_path.0 {
                std::mem::swap(&mut self.best_path.1, &mut self.path_buf);
            }
        }

        // Swap pheromone trails
        self.use_map_b = !self.use_map_b;
    }

    /// Gets the best path ever discovered or `None` if no paths were ever explored.
    pub fn best_path(&self) -> Option<(f32, &[usize])> {
        let (fitness, path) = &self.best_path;
        if *fitness > 0. {
            Some((*fitness, path.as_slice()))
        } else {
            None
        }
    }
}

#[derive(Debug, Copy, Clone, Hash, Eq, PartialEq)]
struct EdgeKey(usize, usize);

impl EdgeKey {
    pub fn new(a: usize, b: usize) -> Self {
        if a < b {
            Self(a, b)
        } else {
            Self(b, a)
        }
    }
}

#[derive(Debug, Copy, Clone)]
struct Edge {
    pheromones: [f32; 2],
}

impl Edge {
    pub fn get_pheromone(&self, use_b: bool) -> f32 {
        self.pheromones[use_b as usize]
    }

    pub fn get_pheromone_mut(&mut self, use_b: bool) -> &mut f32 {
        &mut self.pheromones[use_b as usize]
    }

    pub fn copy_pheromones(&mut self, into_b: bool) {
        let [a, b] = &mut self.pheromones;

        if into_b {
            *b = *a;
        } else {
            *a = *b;
        }
    }
}

#[derive(Debug, Copy, Clone, Default)]
pub struct Dummy;

impl Iterator for Dummy {
    type Item = (f32, usize);

    fn next(&mut self) -> Option<Self::Item> {
        unimplemented!()
    }
}

impl Visitor for Dummy {
    type TargetIter = Dummy;

    fn reset(&mut self) -> usize {
        unimplemented!()
    }

    fn targets(&self, _: usize) -> Self::TargetIter {
        unimplemented!()
    }

    fn walk_to(&mut self, _: usize) {
        unimplemented!()
    }
}

impl Evaluator for Dummy {
    fn edge_quality(&self, _: f32, _: f32) -> f32 {
        unimplemented!()
    }

    fn pheromones_deposited(&self, _: f32) -> f32 {
        unimplemented!()
    }
}
