mod tsp;

fn main() {
    let mut colony = tsp::Colony::new();
    colony.run(1000, &mut tsp::Dummy, &tsp::Dummy);
    println!("{:?}", colony.best_path());
}
