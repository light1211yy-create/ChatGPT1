"""UI-independent orchestration, injectable generator, save only valid results."""
from studio.generator import PlanningContext, ThemeGenerator, get_generator, validate_drafts


def generate_and_save(store, context: PlanningContext, generator: ThemeGenerator | None = None):
    provider = generator if generator is not None else get_generator()
    drafts = provider.generate(context, store.performance())
    validate_drafts(drafts)
    return store.save_batch(context, provider.name, drafts)
