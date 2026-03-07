import { Header } from '../../components/Header';
import { Plus, Edit, Trash2, Users, BookOpen, BarChart, TrendingUp, Award, Clock, Search, Filter, MoreVertical, Eye } from 'lucide-react';
import { useState } from 'react';

export default function AdminDashboard() {
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');

  const courses = [
    { id: 1, name: 'Python 101', students: 45, lessons: 12, status: 'Active', completion: 78, revenue: '$2,340' },
    { id: 2, name: 'JavaScript Basics', students: 32, lessons: 10, status: 'Active', completion: 65, revenue: '$1,920' },
    { id: 3, name: 'Data Structures', students: 18, lessons: 15, status: 'Draft', completion: 0, revenue: '$0' },
    { id: 4, name: 'Web Development', students: 56, lessons: 20, status: 'Active', completion: 82, revenue: '$3,360' },
    { id: 5, name: 'Machine Learning', students: 24, lessons: 18, status: 'Active', completion: 45, revenue: '$1,680' },
  ];

  const stats = [
    {
      label: 'Total Students',
      value: '175',
      icon: Users,
      change: '+12%',
      trend: 'up',
      color: 'from-secondary to-accent'
    },
    {
      label: 'Active Courses',
      value: '4',
      icon: BookOpen,
      change: '+1',
      trend: 'up',
      color: 'from-accent to-primary'
    },
    {
      label: 'Avg. Completion',
      value: '67%',
      icon: BarChart,
      change: '+5%',
      trend: 'up',
      color: 'from-primary to-secondary'
    },
    {
      label: 'Total Revenue',
      value: '$9.3K',
      icon: TrendingUp,
      change: '+18%',
      trend: 'up',
      color: 'from-secondary to-accent'
    },
  ];

  const recentActivities = [
    { user: 'Sarah Chen', action: 'completed', course: 'Python 101', time: '2 hours ago' },
    { user: 'Mike Johnson', action: 'enrolled in', course: 'Web Development', time: '4 hours ago' },
    { user: 'Emma Wilson', action: 'started', course: 'Machine Learning', time: '5 hours ago' },
    { user: 'Alex Brown', action: 'completed', course: 'JavaScript Basics', time: '1 day ago' },
  ];

  const filteredCourses = courses.filter(course => {
    const matchesSearch = course.name.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesFilter = filterStatus === 'all' || course.status.toLowerCase() === filterStatus.toLowerCase();
    return matchesSearch && matchesFilter;
  });

  return (
    <>
      <Header
        title="Admin Dashboard"
        subtitle="Manage courses, students, and content"
      />

      <div className="flex-1 overflow-y-auto">
        <div className="p-8 max-w-[1600px] mx-auto">
          {/* Stats Overview */}
          <section className="mb-8">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              {stats.map((stat, index) => {
                const Icon = stat.icon;
                return (
                  <div
                    key={index}
                    className="bg-card rounded-2xl border-2 border-border p-6 hover:shadow-lg hover:border-secondary/30 transition-all group"
                  >
                    <div className="flex items-start justify-between mb-4">
                      <div className={`w-14 h-14 rounded-xl bg-gradient-to-br ${stat.color} flex items-center justify-center shadow-lg group-hover:scale-110 transition-transform`}>
                        <Icon size={28} className="text-white" />
                      </div>
                      <div className="flex items-center gap-1 px-2 py-1 bg-green-50 text-green-600 rounded-lg text-xs font-semibold">
                        <TrendingUp size={12} />
                        <span>{stat.change}</span>
                      </div>
                    </div>
                    <h2 className="mb-1">{stat.value}</h2>
                    <p className="text-sm text-muted-foreground">{stat.label}</p>
                  </div>
                );
              })}
            </div>
          </section>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Course Management - Takes 2 columns */}
            <div className="lg:col-span-2 space-y-6">
              {/* Course Management Header */}
              <div className="bg-card rounded-2xl border-2 border-border overflow-hidden">
                <div className="px-6 py-5 border-b border-border bg-gradient-to-r from-primary/5 to-secondary/5">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="mb-1">Course Management</h3>
                      <p className="text-sm text-muted-foreground">Manage and monitor all courses</p>
                    </div>
                    <button className="px-5 py-2.5 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all flex items-center gap-2 group">
                      <Plus size={18} className="group-hover:rotate-90 transition-transform" />
                      <span>New Course</span>
                    </button>
                  </div>
                </div>

                {/* Search and Filter */}
                <div className="px-6 py-4 border-b border-border bg-muted/30">
                  <div className="flex gap-4">
                    <div className="flex-1 relative">
                      <Search size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
                      <input
                        type="text"
                        placeholder="Search courses..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full pl-12 pr-4 py-2.5 bg-background border-2 border-border rounded-xl focus:outline-none focus:border-secondary transition-colors"
                      />
                    </div>
                    <div className="relative">
                      <Filter size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
                      <select
                        value={filterStatus}
                        onChange={(e) => setFilterStatus(e.target.value)}
                        className="pl-12 pr-8 py-2.5 bg-background border-2 border-border rounded-xl focus:outline-none focus:border-secondary transition-colors appearance-none cursor-pointer"
                      >
                        <option value="all">All Status</option>
                        <option value="active">Active</option>
                        <option value="draft">Draft</option>
                      </select>
                    </div>
                  </div>
                </div>

                {/* Courses Table */}
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-muted/50 border-b-2 border-border">
                      <tr>
                        <th className="px-6 py-4 text-left text-sm font-semibold">Course</th>
                        <th className="px-6 py-4 text-left text-sm font-semibold">Students</th>
                        <th className="px-6 py-4 text-left text-sm font-semibold">Lessons</th>
                        <th className="px-6 py-4 text-left text-sm font-semibold">Completion</th>
                        <th className="px-6 py-4 text-left text-sm font-semibold">Status</th>
                        <th className="px-6 py-4 text-left text-sm font-semibold">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredCourses.map((course, index) => (
                        <tr
                          key={course.id}
                          className="border-b border-border hover:bg-muted/30 transition-colors group"
                        >
                          <td className="px-6 py-4">
                            <div>
                              <h5 className="mb-1 group-hover:text-secondary transition-colors">{course.name}</h5>
                              <p className="text-xs text-muted-foreground">{course.revenue} revenue</p>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-2">
                              <Users size={16} className="text-muted-foreground" />
                              <span className="font-mono font-semibold">{course.students}</span>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-2">
                              <BookOpen size={16} className="text-muted-foreground" />
                              <span className="font-mono font-semibold">{course.lessons}</span>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-3">
                              <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden max-w-[80px]">
                                <div
                                  className="h-full bg-gradient-to-r from-secondary to-accent rounded-full transition-all"
                                  style={{ width: `${course.completion}%` }}
                                />
                              </div>
                              <span className="text-sm font-mono font-semibold min-w-[40px]">{course.completion}%</span>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <span
                              className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${course.status === 'Active'
                                ? 'bg-green-50 text-green-700 border border-green-200'
                                : 'bg-yellow-50 text-yellow-700 border border-yellow-200'
                                }`}
                            >
                              {course.status}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex gap-2">
                              <button className="p-2 rounded-lg border-2 border-border hover:border-secondary hover:bg-secondary/5 transition-all" title="View">
                                <Eye size={16} />
                              </button>
                              <button className="p-2 rounded-lg border-2 border-border hover:border-accent hover:bg-accent/5 transition-all" title="Edit">
                                <Edit size={16} />
                              </button>
                              <button className="p-2 rounded-lg border-2 border-border hover:border-destructive hover:bg-destructive/5 hover:text-destructive transition-all" title="Delete">
                                <Trash2 size={16} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {filteredCourses.length === 0 && (
                  <div className="px-6 py-12 text-center">
                    <BookOpen size={48} className="mx-auto mb-4 text-muted-foreground opacity-50" />
                    <p className="text-muted-foreground">No courses found</p>
                  </div>
                )}
              </div>

              {/* Quick Add Course Form */}
              <div className="bg-card rounded-2xl border-2 border-border overflow-hidden">
                <div className="px-6 py-4 border-b border-border bg-gradient-to-r from-accent/5 to-primary/5">
                  <h3 className="mb-0">Quick Add Course</h3>
                </div>
                <div className="p-6">
                  <form className="space-y-5">
                    <div>
                      <label htmlFor="courseName" className="block mb-2 text-sm font-semibold">Course Name</label>
                      <input
                        id="courseName"
                        type="text"
                        placeholder="e.g., Python for Data Science"
                        className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                      />
                    </div>

                    <div>
                      <label htmlFor="description" className="block mb-2 text-sm font-semibold">Description</label>
                      <textarea
                        id="description"
                        placeholder="Brief course description..."
                        rows={3}
                        className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors resize-none"
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label htmlFor="lessons" className="block mb-2 text-sm font-semibold">Lessons</label>
                        <input
                          id="lessons"
                          type="number"
                          placeholder="12"
                          className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                        />
                      </div>
                      <div>
                        <label htmlFor="difficulty" className="block mb-2 text-sm font-semibold">Difficulty</label>
                        <select
                          id="difficulty"
                          className="w-full px-4 py-3 border-2 border-border rounded-xl bg-input-background focus:outline-none focus:border-secondary transition-colors"
                        >
                          <option>Beginner</option>
                          <option>Intermediate</option>
                          <option>Advanced</option>
                        </select>
                      </div>
                    </div>

                    <button
                      type="submit"
                      className="w-full py-3 bg-gradient-to-r from-secondary to-accent text-white rounded-xl font-semibold hover:shadow-lg transition-all"
                    >
                      Create Course
                    </button>
                  </form>
                </div>
              </div>
            </div>

            {/* Right Sidebar - Activity & Quick Stats */}
            <div className="space-y-6">
              {/* Top Performers */}
              <div className="bg-card rounded-2xl border-2 border-border overflow-hidden">
                <div className="px-6 py-4 border-b border-border bg-gradient-to-r from-secondary/5 to-accent/5">
                  <h4 className="mb-0 flex items-center gap-2">
                    <Award size={20} className="text-accent" />
                    Top Performers
                  </h4>
                </div>
                <div className="p-4">
                  <div className="space-y-3">
                    {[
                      { name: 'Sarah Chen', score: 98, course: 'Python 101', avatar: 'SC' },
                      { name: 'Mike Johnson', score: 95, course: 'Web Dev', avatar: 'MJ' },
                      { name: 'Emma Wilson', score: 92, course: 'JS Basics', avatar: 'EW' },
                    ].map((student, index) => (
                      <div key={index} className="flex items-center gap-3 p-3 rounded-xl bg-muted/30 hover:bg-muted/50 transition-colors">
                        <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${index === 0 ? 'from-secondary to-accent' :
                          index === 1 ? 'from-accent to-primary' :
                            'from-primary to-secondary'
                          } flex items-center justify-center text-white font-bold text-sm flex-shrink-0`}>
                          {student.avatar}
                        </div>
                        <div className="flex-1 min-w-0">
                          <h5 className="mb-0 text-sm truncate">{student.name}</h5>
                          <p className="text-xs text-muted-foreground truncate">{student.course}</p>
                        </div>
                        <div className="text-right">
                          <p className="font-bold text-lg text-secondary">{student.score}</p>
                          <p className="text-xs text-muted-foreground">score</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Recent Activity */}
              <div className="bg-card rounded-2xl border-2 border-border overflow-hidden">
                <div className="px-6 py-4 border-b border-border bg-gradient-to-r from-primary/5 to-secondary/5">
                  <h4 className="mb-0 flex items-center gap-2">
                    <Clock size={20} className="text-primary" />
                    Recent Activity
                  </h4>
                </div>
                <div className="p-4">
                  <div className="space-y-3">
                    {recentActivities.map((activity, index) => (
                      <div key={index} className="flex items-start gap-3 pb-3 border-b border-border last:border-0 last:pb-0">
                        <div className="w-2 h-2 rounded-full bg-secondary mt-2 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm mb-1">
                            <span className="font-semibold">{activity.user}</span>
                            <span className="text-muted-foreground"> {activity.action} </span>
                            <span className="font-semibold text-secondary">{activity.course}</span>
                          </p>
                          <p className="text-xs text-muted-foreground">{activity.time}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Quick Stats Card */}
              <div className="bg-gradient-to-br from-primary via-secondary to-accent rounded-2xl p-6 text-white shadow-xl">
                <h4 className="mb-4 text-white">This Month</h4>
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-white/90">New Enrollments</span>
                    <span className="text-2xl font-bold">42</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-white/90">Completed Courses</span>
                    <span className="text-2xl font-bold">28</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-white/90">Avg. Rating</span>
                    <span className="text-2xl font-bold">4.8</span>
                  </div>
                </div>
                <div className="mt-6 pt-4 border-t border-white/20">
                  <button className="w-full py-2.5 bg-white/20 hover:bg-white/30 backdrop-blur-sm rounded-lg font-semibold transition-all">
                    View Full Report
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
