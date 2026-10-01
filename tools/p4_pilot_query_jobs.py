"""Create exclusive query job copies, retaining every frozen input binding."""
from tools import p4_exact_pilot as pilot


def main():
    for model, source in (('a', 'configs/p4-pilot-job-a-retry1.json'),
                          ('b', 'configs/p4-pilot-job-b.json')):
        job = pilot.load(pilot.local(source))
        job['output'] = f'build/p4/continuation-dense-{model}-query.json'
        pilot.save(pilot.local(f'configs/p4-pilot-query-{model}.json'), job)


if __name__ == '__main__':
    main()
